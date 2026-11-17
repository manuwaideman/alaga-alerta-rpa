"""Orquestração do processo: entradas -> repetição por bairro -> decisão -> alerta -> banco -> resumo."""
from dataclasses import dataclass
from datetime import timedelta

from .coleta import (ArquivoInvalido, ErroColeta, chuva_com_cache, filtrar_vigentes,
                     ler_boletim, ler_leituras_sensor, ler_ouro)
from .config import BAIRROS
from .db import NIVEIS
from .decisao import decidir
from .mvp import ErroMVP
from .notificador import ErroEnvio, montar_mensagem
from .util import com_retry, hora_cheia, mascarar


@dataclass
class Resumo:
    processados: int = 0
    sucessos: int = 0
    falhas: int = 0
    sem_alerta: int = 0
    alertas_novos: int = 0
    duplicados: int = 0
    enviados: int = 0
    envio_pendente: int = 0
    reenviados: int = 0
    publicados_mvp: int = 0
    publicacao_pendente: int = 0


def _carregar_csv(leitor, caminho, nome, log):
    """Entrada opcional: ausente ou inválida vira aviso/erro no log e o robô segue sem ela."""
    try:
        r = leitor(caminho)
        log.info("%s lido: %d linhas, %d inválidas, %d duplicadas", nome, r.lidas, r.invalidas, r.duplicadas)
        return r, 0
    except FileNotFoundError:
        log.warning("%s ausente (%s): seguindo sem essa fonte", nome, caminho.name)
    except ArquivoInvalido as e:
        log.error("%s inválido: %s: seguindo sem essa fonte", nome, e)
    return None, 1


def _vigentes(entrada, nome, inicio, fim, log):
    """Descarta linhas fora da janela de validade (dado velho ou de outro dia não decide)."""
    if entrada is None:
        return {}
    vigentes, velhos = filtrar_vigentes(entrada, inicio, fim)
    if velhos:
        log.warning("%s: %d linha(s) fora da validade ignorada(s): %s", nome, len(velhos), ", ".join(sorted(velhos)))
    return vigentes


def _publicar_mvp(conn, mvp, cfg, id_alerta, bairro, nivel, motivos, canal, log, dormir):
    """Publica o alerta na API central do MVP com retentativas. Falha -> fica para a próxima execução."""
    try:
        id_mvp = com_retry(lambda: mvp.publicar_alerta(bairro, nivel, motivos, cfg.janela_horas, canal),
                           cfg.tentativas, cfg.espera_base_s, dormir, (ErroMVP,), log, f"publicação MVP #{id_alerta}")
    except ErroMVP as e:
        log.error("Alerta #%d NÃO publicado no MVP, será republicado na próxima execução: %s", id_alerta, e)
        return False
    conn.execute("UPDATE alertas SET publicado_mvp = 1, id_mvp = ? WHERE id = ?", (id_mvp, id_alerta))
    conn.commit()
    log.info("%s: alerta #%d publicado no MVP (id %s)", bairro, id_alerta, id_mvp)
    return True


def _enviar_e_marcar(conn, notificador, cfg, id_alerta, texto, log, dormir):
    """Envia com retentativas. Sucesso -> 'enviado'; falha -> continua 'pendente' (reenvio na próxima execução)."""
    conn.execute("UPDATE alertas SET tentativas = tentativas + 1, canal = ? WHERE id = ?", (notificador.canal, id_alerta))
    try:
        com_retry(lambda: notificador.enviar(texto), cfg.tentativas, cfg.espera_base_s, dormir,
                  (ErroEnvio,), log, f"envio alerta #{id_alerta}")
        conn.execute("UPDATE alertas SET status_envio = 'enviado' WHERE id = ?", (id_alerta,))
        conn.commit()
        return True
    except ErroEnvio as e:
        log.error("Alerta #%d NÃO enviado, ficou pendente para a próxima execução: %s", id_alerta, e)
        conn.commit()
        return False


def executar(cfg, conn, provedor_chuva, notificador, agora, log, dormir, mvp=None):
    """provedor_chuva(bairro, lat, lon) -> mm. mvp: ClienteMVP ou None. Retorna Resumo."""
    res = Resumo()
    log.info("Início da execução | canal=%s | referência=%s | MVP=%s", notificador.canal, hora_cheia(agora),
             "integrado" if mvp else "desativado")
    if notificador.canal == "telegram":
        log.info("Telegram configurado (chat %s)", mascarar(cfg.telegram_chat_id))

    # 0) Republica no MVP os alertas recentes que não chegaram lá (MVP estava fora do ar)
    if mvp:
        recente = hora_cheia(agora - timedelta(hours=cfg.janela_horas))
        for p in conn.execute("SELECT * FROM alertas WHERE publicado_mvp = 0 AND hora_ref >= ?", (recente,)).fetchall():
            if _publicar_mvp(conn, mvp, cfg, p["id"], p["bairro"], p["nivel"], [p["motivo"]],
                             p["canal"] or notificador.canal, log, dormir):
                res.publicados_mvp += 1
            else:
                res.publicacao_pendente += 1

    # 1) Reenvia o que ficou pendente em execuções anteriores
    for p in conn.execute("SELECT * FROM alertas WHERE status_envio = 'pendente'").fetchall():
        texto = montar_mensagem(p["bairro"], p["nivel"], [p["motivo"]], p["hora_ref"])
        if _enviar_e_marcar(conn, notificador, cfg, p["id"], texto, log, dormir):
            res.reenviados += 1
            log.info("Alerta pendente #%d reenviado (%s, %s)", p["id"], p["bairro"], p["nivel"])

    # 2) Entradas em arquivo e leituras do robô físico
    boletim_e, f1 = _carregar_csv(ler_boletim, cfg.boletim_csv, "Boletim CGE", log)
    ouro_e, f2 = _carregar_csv(ler_ouro, cfg.ouro_csv, "Tabela Ouro", log)
    boletim = _vigentes(boletim_e, "Boletim CGE", agora - timedelta(hours=cfg.boletim_validade_h),
                        agora + timedelta(hours=1), log)
    ouro = _vigentes(ouro_e, "Tabela Ouro", agora - timedelta(hours=1),
                     agora + timedelta(hours=cfg.janela_horas), log)
    res.falhas += f1 + f2

    sensores = ler_leituras_sensor(conn, agora, cfg.leitura_validade_min)
    if mvp:
        try:
            do_mvp = mvp.leituras(agora, cfg.leitura_validade_min)
            log.info("Leituras de sensor recebidas do MVP: %d", len(do_mvp))
            for bairro, nivel in do_mvp.items():  # vale a mais grave entre banco local e MVP
                if NIVEIS.index(nivel) > NIVEIS.index(sensores.get(bairro, "normal")):
                    sensores[bairro] = nivel
        except ErroMVP as e:
            res.falhas += 1
            log.error("Leituras do MVP indisponíveis: %s (seguindo com as leituras locais)", e)
    log.info("Leituras de sensor válidas: %d", len(sensores))

    # 3) Repetição: um ciclo por bairro
    for bairro, (lat, lon) in BAIRROS.items():
        res.processados += 1
        try:
            mm, origem = chuva_com_cache(bairro, lambda: provedor_chuva(bairro, lat, lon), cfg, agora, log, dormir)
        except ErroColeta as e:
            mm, origem = None, "indisponivel"
            res.falhas += 1
            log.error("Falha na chuva de %s: %s (decidindo só com as outras fontes)", bairro, e)

        d = decidir(mm, boletim.get(bairro), ouro.get(bairro), sensores.get(bairro), cfg)
        if d.nivel == "normal":
            res.sem_alerta += 1
            if origem != "indisponivel":
                res.sucessos += 1
            log.info("%s: normal (chuva %s, origem=%s), sem alerta", bairro, f"{mm} mm" if mm is not None else "n/d", origem)
            continue
        if origem != "indisponivel":
            res.sucessos += 1

        # 4) Grava (UNIQUE evita duplicar o mesmo alerta na mesma hora)
        hora_ref = hora_cheia(agora)
        cur = conn.execute(
            "INSERT OR IGNORE INTO alertas (bairro, nivel, motivo, chuva_mm, hora_ref, criado_em) VALUES (?,?,?,?,?,?)",
            (bairro, d.nivel, "; ".join(d.motivos), mm, hora_ref, agora.isoformat(timespec="seconds")))
        conn.commit()
        if cur.rowcount == 0:
            res.duplicados += 1
            log.info("%s: alerta %s já existe para %s, ignorado (duplicado)", bairro, d.nivel, hora_ref)
            continue
        res.alertas_novos += 1
        log.info("%s: ALERTA %s gravado (%s)", bairro, d.nivel.upper(), "; ".join(d.motivos))

        # 5) Dispara no canal
        texto = montar_mensagem(bairro, d.nivel, d.motivos, hora_ref)
        if _enviar_e_marcar(conn, notificador, cfg, cur.lastrowid, texto, log, dormir):
            res.enviados += 1
            log.info("%s: alerta enviado via %s", bairro, notificador.canal)
        else:
            res.envio_pendente += 1

        # 6) Integração: publica na API central para aparecer no site do MVP
        if mvp:
            if _publicar_mvp(conn, mvp, cfg, cur.lastrowid, bairro, d.nivel, d.motivos, notificador.canal, log, dormir):
                res.publicados_mvp += 1
            else:
                res.publicacao_pendente += 1

    # 7) Auditoria
    conn.execute(
        "INSERT INTO execucoes (inicio, fim, processados, sucessos, falhas, alertas_novos, duplicados, enviados, pendentes)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (agora.isoformat(timespec="seconds"), agora.isoformat(timespec="seconds"), res.processados, res.sucessos,
         res.falhas, res.alertas_novos, res.duplicados, res.enviados, res.envio_pendente))
    conn.commit()
    log.info("Fim | processados=%d sucessos=%d falhas=%d alertas_novos=%d duplicados=%d enviados=%d pendentes=%d "
             "reenviados=%d sem_alerta=%d publicados_mvp=%d publicacao_pendente=%d",
             res.processados, res.sucessos, res.falhas, res.alertas_novos, res.duplicados, res.enviados,
             res.envio_pendente, res.reenviados, res.sem_alerta, res.publicados_mvp, res.publicacao_pendente)
    return res
