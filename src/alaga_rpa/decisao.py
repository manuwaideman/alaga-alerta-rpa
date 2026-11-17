"""Regra de negócio: o risco final é o MAIOR entre chuva prevista, boletim, Ouro e sensor."""
from dataclasses import dataclass, field

from .db import NIVEIS


@dataclass
class Decisao:
    nivel: str = "normal"
    motivos: list = field(default_factory=list)


def classificar_chuva(mm, limiar_atencao, limiar_perigo):
    if mm is None:
        return "normal"
    if mm >= limiar_perigo:
        return "perigo"
    if mm >= limiar_atencao:
        return "atencao"
    return "normal"


def decidir(chuva_mm, boletim, ouro, sensor, cfg):
    """Cada fonte vota um nível; vale o mais alto. Registra o motivo de cada voto acima de 'normal'."""
    votos = [
        (classificar_chuva(chuva_mm, cfg.limiar_atencao_mm, cfg.limiar_perigo_mm),
         f"chuva prevista {chuva_mm} mm em {cfg.janela_horas}h"),
        (boletim or "normal", "boletim CGE/Defesa Civil"),
        (ouro or "normal", "risco da tabela Ouro (Big Data)"),
        (sensor or "normal", "sensor de nível de água (robô)"),
    ]
    d = Decisao()
    for nivel, motivo in votos:
        if NIVEIS.index(nivel) > NIVEIS.index(d.nivel):
            d.nivel = nivel
        if nivel != "normal":
            d.motivos.append(f"{motivo}: {nivel}")
    return d
