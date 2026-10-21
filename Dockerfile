FROM python:3.10-slim

# Install system dependencies and SQL Server ODBC driver
RUN apt-get update && apt-get install -y curl apt-transport-https gnupg2 unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc > /etc/apt/trusted.gpg.d/microsoft.asc \
    && curl -fsSL https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql17

# Set the working directory
WORKDIR /app

# Copy project files#
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Default command when running the container
CMD ["python", "src/01_etl_and_normalization.py"]