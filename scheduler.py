"""Agendador da coleta diária do Radar Cordeiro (08:00, America/Fortaleza).

    python scheduler.py           # fica rodando e dispara todo dia às 08:00
    python scheduler.py --agora   # executa uma coleta imediatamente e continua agendado
"""
from __future__ import annotations

import argparse
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from radar import config
from radar.collector import log, run_collection, setup_logging

HOUR = int(os.getenv("RADAR_HORA", "8"))
MINUTE = int(os.getenv("RADAR_MINUTO", "0"))


def job() -> None:
    try:
        run_collection("agendado")
    except Exception:  # o agendador nunca deve morrer por causa de uma coleta
        log.exception("Erro não tratado na coleta agendada")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agora", action="store_true", help="executa uma coleta ao iniciar")
    args = parser.parse_args()

    setup_logging()
    scheduler = BlockingScheduler(timezone=config.TZ)
    scheduler.add_job(
        job,
        CronTrigger(hour=HOUR, minute=MINUTE, timezone=config.TZ),
        id="coleta_diaria",
        misfire_grace_time=3 * 3600,  # se a máquina estava suspensa, ainda roda até 3h depois
        coalesce=True,
        max_instances=1,
    )
    if args.agora:
        job()
    next_run = scheduler.get_jobs()[0].trigger.get_next_fire_time(None, config.now())
    log.info("Agendador ativo. Próxima coleta: %s (%s). Ctrl+C para encerrar.", next_run, config.TZ.key)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Agendador encerrado.")


if __name__ == "__main__":
    main()
