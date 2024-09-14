import sys
import asyncio

# 設置事件循環策略（放在最前面）
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import discord
from discord.ext import commands
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import os

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置 Bybit API
bybit = ccxt.bybit({
    'enableRateLimit': True,
})

# Discord 機器人設置
intents = discord.Intents.default()
intents.message_content = True  # 確保機器人能讀取訊息內容

bot = commands.Bot(command_prefix='!', intents=intents)

# Fibonacci 比例
fib_ratios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
strong_gravity = [0.236, 0.382, 0.618, 0.786]
weak_gravity = [0.5, 1]

def classify_candle(row):
    """分類 K 線"""
    open_price = row['open']
    close_price = row['close']
    high = row['high']
    low = row['low']
    
    if close_price > open_price:
        upper_shadow = high - close_price
        lower_shadow = open_price - low
        if upper_shadow <= 4 * (close_price - open_price):
            return 'bullish_volume'
    elif close_price < open_price:
        upper_shadow = high - open_price
        lower_shadow = close_price - low
        if lower_shadow <= 4 * (open_price - close_price):
            return 'bearish_volume'
    return 'neutral'

def calculate_fibonacci_levels(high, low):
    """計算 Fibonacci 引力位"""
    diff = high - low
    levels = [low + diff * ratio for ratio in fib_ratios]
    return levels

def classify_gravity(levels):
    """分類引力位"""
    gravity_classification = {}
    for i, level in enumerate(levels):
        ratio = fib_ratios[i]
        if ratio in strong_gravity:
            gravity_classification[level] = 'strong'
        elif ratio in weak_gravity:
            gravity_classification[level] = 'weak'
    return gravity_classification

def determine_trend(volume_data):
    """判斷趨勢"""
    bullish_volumes = [v['bullish'] for v in volume_data]
    bearish_volumes = [v['bearish'] for v in volume_data]
    
    bullish_trend = all(bullish_volumes[i] >= bullish_volumes[i-1] for i in range(1, len(bullish_volumes)))
    bearish_trend = all(bearish_volumes[i] >= bearish_volumes[i-1] for i in range(1, len(bearish_volumes)))
    
    if bullish_trend and not bearish_trend:
        return 'bullish_strength'
    elif bearish_trend and not bullish_trend:
        return 'bearish_strength'
    else:
        return 'balanced'

def determine_trade_signal(current_price, gravity_levels, current_volume, avg_volume):
    """判斷交易信號"""
    threshold = 50  # 調整根據具體需求，例如 50 美元範圍內
    high_volume = current_volume > avg_volume
    
    for level, gravity_type in gravity_levels.items():
        if abs(current_price - level) < threshold:
            if gravity_type == 'strong':
                if not high_volume:
                    return 'buy' if current_price < level else 'sell'
            elif gravity_type == 'weak':
                if not high_volume:
                    return 'buy' if current_price < level else 'sell'
                else:
                    pass  # 可根據具體策略添加更多條件
    return 'hold'

def check_volume_spike(current_volume, avg_volume, next_candle_classification):
    """處理成交量異動"""
    if current_volume > avg_volume:
        if next_candle_classification == 'bullish_volume':
            return 'bullish_trend'
        elif next_candle_classification == 'bearish_volume':
            return 'bearish_trend'
    return 'trend_continues'

@bot.command(name='analyze', help='分析指定的 Bybit 交易對。用法：!analyze BTC/USDT')
async def analyze(ctx, symbol: str):
    """分析指定的 Bybit 交易對並發送結果到 Discord 頻道"""
    try:
        # 標準化交易對格式
        symbol = symbol.upper().replace('-', '/')
        
        # 獲取最近 4 個月的 K 線數據（四小時周期）
        since = bybit.parse8601((datetime.utcnow() - timedelta(days=120)).strftime('%Y-%m-%dT%H:%M:%SZ'))
        ohlcv = bybit.fetch_ohlcv(symbol, '4h', since=since)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # 確保有足夠的數據
        if len(df) < 42:
            await ctx.send("數據不足，無法進行分析。")
            return
        
        # 分類每根 K 線
        df['classification'] = df.apply(classify_candle, axis=1)
        
        # 計算平均成交量（最近 42 根 K 線）
        df['avg_volume'] = df['volume'].rolling(window=42).mean()
        
        # 準備趨勢判斷
        volume_data = [{'bullish': row['volume'] if row['classification'] == 'bullish_volume' else 0,
                       'bearish': row['volume'] if row['classification'] == 'bearish_volume' else 0}
                      for _, row in df.iterrows()]
        trend = determine_trend(volume_data[-42:])  # 使用最近 42 根 K 線
        
        # 計算引力位（基於最近 3-4 個月的高低點）
        high = df['high'].max()
        low = df['low'].min()
        fib_levels = calculate_fibonacci_levels(high, low)
        gravity_levels = classify_gravity(fib_levels)
        
        # 當前價格和成交量
        current_price = df['close'].iloc[-1]
        current_volume = df['volume'].iloc[-1]
        avg_volume = df['avg_volume'].iloc[-1]
        
        # 判斷交易信號
        signal = determine_trade_signal(current_price, gravity_levels, current_volume, avg_volume)
        
        # 檢查成交量異動
        if len(df) >= 2:
            prev_volume = df['volume'].iloc[-2]
            prev_classification = df['classification'].iloc[-2]
            trend_change = check_volume_spike(prev_volume, avg_volume, df['classification'].iloc[-1])
            if trend_change == 'bullish_trend':
                signal = 'buy'
            elif trend_change == 'bearish_trend':
                signal = 'sell'
        
        # 準備發送的消息
        embed = discord.Embed(title=f"分析結果：{symbol}", color=0x00ff00)
        embed.add_field(name="當前價格", value=f"{current_price}", inline=False)
        embed.add_field(name="趨勢判斷", value=f"{trend}", inline=False)
        embed.add_field(name="交易信號", value=f"{signal}", inline=False)
        
        # 添加引力位
        gravity_info = ""
        for level, gravity_type in gravity_levels.items():
            gravity_info += f"**{gravity_type.capitalize()} 引力位**: {level}\n"
        embed.add_field(name="引力位", value=gravity_info, inline=False)
        
        # 發送消息
        await ctx.send(embed=embed)
        
    except ccxt.BaseError as e:
        logging.error(f"CCXT Error: {e}")
        await ctx.send("與 Bybit 交互時出現錯誤，請檢查交易對是否正確或稍後再試。")
    except Exception as e:
        logging.error(f"Error during analysis: {e}")
        await ctx.send("分析過程中出現錯誤，請稍後再試。")

# 啟動機器人
bot.run('token')
