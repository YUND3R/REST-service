HTTP/2 (TLS) и mTLS между кластерами (edge → ml-balancer)
==========================================================

Кластер B по умолчанию — только в доверенном сетевом контуре (см. deploy/k8s/clusters/README.txt).
Overlay ниже не отменяет этого правила: TLS/mTLS добавляет шифрование и идентификацию на канале
A→B (в том числе внутри частной сети / при сегментации). Публичного доступа к ml-balancer по-прежнему
не предполагается.

Назначение
----------
- Трафик gateway → ml-balancer идёт по HTTPS на порту 443 с HTTP/2 между двумя nginx
  (мультиплексирование, сжатие header — меньше накладных расходов на «тяжёлые» JSON-тела).
- Опционально: mTLS — ml-balancer проверяет клиентский сертификат gateway.
- Текущие сервисы code-analyze / task-generate остаются HTTP/1.1 за внутренним nginx.

Важно про gRPC
--------------
- Реальный gRPC (protobuf + grpc_pass) возможен только после появления gRPC-эндпойнтов
  в приложениях. Сейчас используется proxy_pass JSON API поверх HTTP/2 между nginx.
- В ml-common-locations.inc есть закомментированный пример grpc_pass.

Секреты (создайте до apply)
----------------------------
Кластер B (ml), namespace edu-ml:

  ml-balancer-server-tls     — тип kubernetes.io/tls (tls.crt, tls.key) — сервер ml-balancer
  gateway-client-ca          — opaque, ключ ca.crt — CA, которым подписан клиентский сертификат gateway

Кластер A (edge), namespace edu-ml:

  ml-server-ca               — opaque, ca.crt — CA, которым подписан сервер ml-balancer
                               (для proxy_ssl_trusted_certificate на gateway)
  gateway-client-tls         — тип kubernetes.io/tls — клиент gateway к ml-balancer

Серверный сертификат ml-balancer должен иметь SAN/CN, совпадающие с hostname, на который
указывает ExternalName (SNI). Подставьте тот же FQDN в edge/files/ml_tls.inc
(директива proxy_ssl_name) и в сертификат.

Применение (из корня репозитория, подставьте путь deploy/k8s/overlays/...)
----------
  kubectl kustomize --load-restrictor=LoadRestrictionsNone deploy/k8s/overlays/intercluster-h2-mtls/ml \
    | kubectl apply -f -
  kubectl kustomize --load-restrictor=LoadRestrictionsNone deploy/k8s/overlays/intercluster-h2-mtls/edge \
    | kubectl apply -f -

Проверка mlTLS: на ml-balancer смените ssl_verify_client optional на on после выдачи клиентских сертификатов.
