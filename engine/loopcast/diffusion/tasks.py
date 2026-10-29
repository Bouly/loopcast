"""Les tâches du module diffusion (file de tâches durable, loopcast/jobs.py).

- diffusion.tick    : l'autopilote, toutes les 10 min, se ré-enfile lui-même (autopilot.py) ; une erreur
                      passagère (base verrouillée en écrivant le tick suivant…) est réessayée 30 s puis 1 min
                      plus tard, et le chien de garde (startup.watchdog) relance la chaîne si elle casse
- diffusion.publish : publie un post dû (executor.py) ; payload {post_id, attempt}
- diffusion.metrics : relève les vues puis cherche les gagnants (metrics.py)

Services lus dans ctx.services : « publishers » (diffusion/services.py, FakePublisher en démo et dans
les tests) et « notify » (facultatif : remplace les notifications macOS/ntfy, pour les tests).
"""

from __future__ import annotations

from loopcast import jobs
from loopcast.diffusion import autopilot, executor, metrics


@jobs.handler("diffusion.tick", max_attempts=3, lease_s=600, backoff_s=(30, 60))
def tick(ctx: jobs.JobContext, payload: dict) -> dict:
    now = ctx.clock()
    autopilot.enqueue_tick(ctx.conn, now, next_slice=True)       # d'abord : la chaîne ne casse jamais
    report = autopilot.run_tick(ctx.conn, ctx.config, now, services=ctx.services, force=bool(payload.get("force")))
    if report["errors"]:
        raise jobs.Permanent("tick incomplet — " + " ; ".join(report["errors"]))
    return report


@jobs.handler("diffusion.publish", max_attempts=3, lease_s=900, backoff_s=(60, 300))
def publish(ctx: jobs.JobContext, payload: dict) -> dict:
    publishers, notifier = autopilot.services_of(ctx.config, ctx.services)
    if "post_id" not in payload:
        raise jobs.Permanent("payload sans post_id")
    return executor.publish_post(ctx.conn, ctx.config, int(payload["post_id"]), publishers=publishers,
                                 clock=ctx.clock, notifier=notifier, attempt=payload.get("attempt"))


@jobs.handler("diffusion.metrics", max_attempts=2, lease_s=900, backoff_s=(300,))
def collect_metrics(ctx: jobs.JobContext, payload: dict) -> dict:
    publishers, _ = autopilot.services_of(ctx.config, ctx.services)
    return metrics.run(ctx.conn, ctx.config, ctx.clock(), publishers=publishers)
