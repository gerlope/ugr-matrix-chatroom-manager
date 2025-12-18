Para excluir un usuario a excepciones de rate limiters:

kubectl -n ess edit configmap ess-synapse

Añadir a los limites que queramos sobrepasar

Recomiendo al menos rc_joins, rc_invites, rc_room_creation

exempt_user_ids:
  - "@username:homeserver.tls"

EJ:

        rc_message:
      # This needs to match at least e2ee key sharing frequency plus headroom
      per_second: 0.2
      burst_count: 10
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_registration:
      per_second: 0.17
      burst_count: 3.0
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_admin_redaction:
      per_second: 1.0
      burst_count: 50.0
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_room_creation:
      per_second: 0.016
      burst_count: 10.0
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_joins:
      local:
        per_second: 0.2
        burst_count: 15.0
      remote:
        per_second: 0.03
        burst_count: 12.0
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_invites:
      per_room:
        per_second: 0.5
        burst_count: 5.0
      per_user:
        per_second: 0.004
        burst_count: 3.0
      per_issuer:
        per_second: 0.5
        burst_count: 5.0
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_presence:
      per_user:
        per_second: 0.1
        burst_count: 1.0
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_login:
      address:
        per_second: 0.15
        burst_count: 5.0
      account:
        per_second: 0.18
        burst_count: 4.0
      failed_attempts:
        per_second: 0.19
        burst_count: 7.0
      exempt_user_ids:
        - "@ugr_bot:jmcastillo.net"

    rc_delayed_event_mgmt:
      # Matches at least the heart-beat frequency plus headroom
      per_second: 1.0
      burst_count: 20.0
      exempt_user_ids:
      - "@ugr_bot:jmcastillo.net"

Cuidado con el formato



kubectl -n ess rollout restart statefulset/ess-synapse-main 