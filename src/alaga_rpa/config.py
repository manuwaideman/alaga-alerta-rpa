"""Configuração central. Segredos vêm só de variáveis de ambiente (nunca do código)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Bairros monitorados (nome -> latitude, longitude). Ajuste conforme o território do produto.
BAIRROS = {
    "Pinheiros": (-23.5670, -46.7010),
    "Lapa": (-23.5217, -46.7014),
    "Penha": (-23.5286, -46.5434),
    "Santo Amaro": (-23.6537, -46.7156),
    "Itaim Paulista": (-23.5011, -46.3992),
    "Jabaquara": (-23.6486, -46.6406),
}

# Nome do bairro no robô -> id do bairro na API central do MVP (GET /bairros).
BAIRRO_ID = {
    "Pinheiros": "pinheiros",
    "Lapa": "lapa",
    "Penha": "penha",
    "Santo Amaro": "santo-amaro",
    "Itaim Paulista": "itaim-paulista",
    "Jabaquara": "jabaquara",
}

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def carregar_env(caminho=None):
    """Lê o arquivo .env (se existir) sem sobrescrever variáveis já definidas no ambiente.
    Assim basta copiar .env.example para .env e preencher; nada vai para o código."""
    caminho = Path(caminho or RAIZ / ".env")
    if not caminho.is_file():
        return 0
    lidas = 0
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, valor = linha.split("=", 1)
        nome, valor = nome.strip(), valor.strip().strip('"').strip("'")
        if nome and valor and nome not in os.environ:
            os.environ[nome] = valor
            lidas += 1
    return lidas


def _float(nome, padrao):
    return float(os.getenv(nome, padrao))


def _int(nome, padrao):
    return int(os.getenv(nome, padrao))


@dataclass
class Config:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("ALAGA_DB", RAIZ / "data" / "alaga.db")))
    logs_dir: Path = field(default_factory=lambda: Path(os.getenv("ALAGA_LOGS", RAIZ / "logs")))
    cache_dir: Path = field(default_factory=lambda: Path(os.getenv("ALAGA_CACHE", RAIZ / "data" / "cache")))
    boletim_csv: Path = field(default_factory=lambda: Path(os.getenv("ALAGA_BOLETIM", RAIZ / "amostras" / "boletim_cge.csv")))
    ouro_csv: Path = field(default_factory=lambda: Path(os.getenv("ALAGA_OURO", RAIZ / "amostras" / "ouro_risco_bairro_hora.csv")))
    previsao_simulada: Path = field(default_factory=lambda: RAIZ / "amostras" / "previsao_simulada.json")
    open_meteo_url: str = OPEN_METEO_URL
    origem_chuva: str = "api"  # "simulado" quando usar a amostra local
    # Regras de negócio (mm de chuva acumulada na janela)
    limiar_atencao_mm: float = field(default_factory=lambda: _float("LIMIAR_ATENCAO_MM", 15))
    limiar_perigo_mm: float = field(default_factory=lambda: _float("LIMIAR_PERIGO_MM", 30))
    janela_horas: int = field(default_factory=lambda: _int("JANELA_HORAS", 3))
    # Resiliência
    tentativas: int = field(default_factory=lambda: _int("TENTATIVAS", 3))
    espera_base_s: float = field(default_factory=lambda: _float("ESPERA_BASE_S", 1))
    cache_validade_h: int = 6
    leitura_validade_min: int = 60
    # Dados velhos não decidem: boletim vale até 6 h; linha da Ouro precisa estar na janela da previsão.
    boletim_validade_h: int = field(default_factory=lambda: _int("BOLETIM_VALIDADE_H", 6))
    # Integração com a API central do MVP (opcional; segredos só por ambiente)
    mvp_url: str = field(default_factory=lambda: os.getenv("MVP_URL", ""))
    mvp_api_key: str = field(default_factory=lambda: os.getenv("MVP_API_KEY", ""))
    # Canal de alerta (segredos só por ambiente)
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
