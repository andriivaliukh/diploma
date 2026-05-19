FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wireguard-tools iproute2 iptables \
 && update-alternatives --set iptables /usr/sbin/iptables-legacy \
 && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY vpnservice/ vpnservice/
COPY alembic.ini .
COPY alembic/ alembic/

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "vpnservice.main:app", "--host", "0.0.0.0", "--port", "8000"]
