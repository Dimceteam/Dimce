FROM python:3.11-slim

# Évite les fichiers .pyc et force les logs non bufferisés (utile pour Streamlit)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances système minimales (scipy/matplotlib ont besoin de ces libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 1. Installer les dépendances Python (mis en cache tant que requirements.txt ne change pas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copier le code et les données
COPY dimce.py .
COPY dimce_app.py .
COPY tableautarif.csv .
COPY DataCE.mat .

# Streamlit écoute par défaut sur 8501
EXPOSE 8501

# Désactiver la télémétrie et le prompt du premier lancement
RUN mkdir -p /root/.streamlit && \
    echo "[browser]\ngatherUsageStats = false\n" > /root/.streamlit/config.toml

CMD ["streamlit", "run", "dimce_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
