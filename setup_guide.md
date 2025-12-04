Para excluir un usuario a excepciones de rate limiters:

kubectl -n ess edit configmap ess-synapse

Añadir a los limites que queramos sobrepasar

exempt_user_ids:
  - "@username:homeserver.tls"

EJ:

rc_joins:
    local:
      per_second: 0.1
      burst_count: 10
    remote:
      per_second: 0.01
      burst_count: 10
    exempt_user_ids:
      - "@ugr_bot:ugr.es"

Cuidado con el formato



kubectl -n ess rollout restart statefulset/ess-synapse-main 