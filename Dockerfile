FROM python:3.12-slim

# Skip Git LFS — server doesn't need data_cache or kite_data
ENV GIT_LFS_SKIP_SMUDGE=1

WORKDIR /app

# Copy only the files the server needs (not the 395MB of LFS data)
COPY dashboard_server.py .
COPY build_kite_dashboard.py .
COPY kite_dashboard.html .
COPY all_strategy_hashes.json .
COPY kite_v16_trades.json .
COPY kite_champion_trades.json .
COPY kite_grade10_trades.json .
COPY kite_rangeonly_trades.json .
COPY kite_v9_trades.json .
COPY kite_v16b_trades.json .

EXPOSE 8877

CMD ["python", "-u", "dashboard_server.py"]
