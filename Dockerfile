FROM python:3.10-slim

# Instalar dependências do sistema e o driver ODBC do SQL Server
RUN apt-get update && apt-get install -y curl apt-transport-https gnupg2 unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc > /etc/apt/trusted.gpg.d/microsoft.asc \
    && curl -fsSL https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql17

# Definir o diretório de trabalho
WORKDIR /app

# Copiar os arquivos do projeto
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Comando padrão ao iniciar o contêiner
CMD ["python", "src/01_etl_and_normalization.py"]
