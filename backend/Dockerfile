FROM python:3.11-slim

WORKDIR /app

# System dependencies for scientific Python stack
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    g++ \
    gfortran \
    liblapack-dev \
    libblas-dev \
    libhdf5-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directories
RUN mkdir -p uploads reports logs

# Non-root user for security
RUN groupadd -r pathdrift && useradd -r -g pathdrift pathdrift
RUN chown -R pathdrift:pathdrift /app
USER pathdrift

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
