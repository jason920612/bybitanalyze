# 使用官方的 Python 3.9 基礎映像
FROM python:3.9-slim

# 設定工作目錄
WORKDIR /app

# 複製 requirements.txt 到容器中
COPY requirements.txt .

# 安裝必要的系統套件
RUN apt-get update && \
    apt-get install -y gcc build-essential && \
    rm -rf /var/lib/apt/lists/*

# 安裝 Python 套件
RUN pip install --no-cache-dir -r requirements.txt

# 複製當前目錄內容到容器內的 /app 目錄
COPY . /app

# 暴露必要的埠（如果有需要）
EXPOSE 8000

# 執行主程式
CMD ["python", "main.py"]
