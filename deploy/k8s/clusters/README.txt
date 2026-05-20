Два Kubernetes-кластера (канонический прод)
============================================

Стандарт деплоя: два физических кластера A (edge) и B (ML). Каталог deploy/k8s/manifests/ содержит
только переиспользуемые фрагменты YAML (нет kustomization.yaml — оттуда сборка не выполняется).
Единственные точки сборки для продакшена: deploy/k8s/clusters/ml и deploy/k8s/clusters/edge
(разные контексты kubectl / kubeconfig).


Кластер A — вход (edge)
-------------------------------------------------
  deploy/k8s/clusters/edge

  Ingress -> Service edge-balancer -> nginx edge -> API Gateway (FastAPI).

  Gateway не вызывает ML по HTTP. Он пишет задачи в Redis Streams и читает статусы/результаты.
  Для связи с кластером B отредактируйте ExternalName-сервисы:
    deploy/k8s/clusters/edge/redis-externalname.yaml
    deploy/k8s/clusters/edge/postgres-externalname.yaml
  Замените redis.ml.example.internal / postgres.ml.example.internal на приватные DNS-имена сервисов кластера B.


Кластер B — Redis + PostgreSQL + GPU workers (контур только с доверенного периметра)
-------------------------------------------------
  deploy/k8s/clusters/ml

  Namespace edu-ml помечен лейблами (см. clusters/ml/namespace-labels.yaml):
    networking.edu-ml.io/contour=private,
    networking.edu-ml.io/cluster-b-ml-tier=true

  В ML-кластере запускаются:
    - redis: Redis Streams, кэш, статусы задач, student_profile
    - postgres: platforms/students/analyses/generated_tasks
    - worker-analyze: модель анализа кода
    - worker-generate: модель генерации задач
    - worker-pipeline: полный цикл "анализ -> профиль -> генерация"

  Старые HTTP ML-сервисы (code-analyze/task-generate), auth-service и ml-balancer не входят в канонический
  минимальный контур. Они могут оставаться в репозитории как legacy/experimental, но не подключаются
  kustomization-файлами clusters/ml и clusters/edge.


Порядок раскладки и команды Kustomize
--------------------------------------

  0) Создайте секреты PostgreSQL/DATABASE_URL в обоих кластерах.
     Пример команд: deploy/k8s/clusters/SECRETS.example.txt

  1) Кластер B (ML):

     kubectl kustomize --load-restrictor=LoadRestrictionsNone deploy/k8s/clusters/ml | kubectl apply -f -

  2) Пропишите доступные из кластера A DNS-имена Redis и PostgreSQL (private DNS / internal LB).

  3) Кластер A (edge):

     kubectl kustomize --load-restrictor=LoadRestrictionsNone deploy/k8s/clusters/edge | kubectl apply -f -

Kustomize по умолчанию не тянет ../.. без --load-restrictor=LoadRestrictionsNone (или аналога в конфиг).


GPU / топология и межкластерная связность
---------------------------------------------------
  deploy/k8s/overlays/cpu-gpu-topology — подпапки ml/ и edge/ (применять в каждом кластере свой kustomize).
  deploy/k8s/overlays/gpu-pool-rtx5000-a100 — то же, разнесение классов GPU.

Требуется приватная сетевое соединение между edge и ML-кластерами (VPC peering/VPN/private DNS/internal LB).
Если используется CNI с NetworkPolicy (Calico, Cilium, AWS VPC CNI + NP и т.д.), ограничения нужно
дублировать правилами на Redis/PostgreSQL. Иначе применяйте security groups / firewall.

Meta: CI
--------
  workflow .github/workflows/deploy-k8s.yml уже применяет сначала clusters/ml, затем clusters/edge
  с разными секретами kubeconfig.
