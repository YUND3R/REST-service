Два Kubernetes-кластера (канонический прод)
============================================

Стандарт деплоя: два физических кластера A (edge) и B (ML). Каталог deploy/k8s/manifests/ содержит
только переиспользуемые фрагменты YAML (нет kustomization.yaml — оттуда сборка не выполняется).
Единственные точки сборки для продакшена: deploy/k8s/clusters/ml и deploy/k8s/clusters/edge
(разные контексты kubectl / kubeconfig).


Кластер A — вход (edge)
-------------------------------------------------
  deploy/k8s/clusters/edge

  Ingress -> Service edge-balancer -> nginx edge -> gateway nginx -> ExternalName-сервис ml-balancer ->
  резолв внутреннего имени до кластера B (см. ml-balancer-externalname.yaml).

  После установки DNS внутренней зоны отредактируйте
  deploy/k8s/clusters/edge/ml-balancer-externalname.yaml: замените externalName вида
  ml-balancer.cluster-b.example.invalid на FQDN / CNAME вашего LB сервиса кластера B.


Кластер B — модели + ml-balancer + Redis (контур только с доверенного периметра)
-------------------------------------------------
  deploy/k8s/clusters/ml

  Namespace edu-ml помечен лейблами (см. clusters/ml/namespace-labels.yaml):
    networking.edu-ml.io/contour=private,
    networking.edu-ml.io/cluster-b-ml-tier=true

NetworkPolicy в manifests/network-policy-ml-tier.yaml описывает доверенный контур между нод-кластерами и
единым kubelet-слоем только для упрощения; между двумя кластерами к ml-balancer идёт трафик с
адресов вашей приватной сети/CGNAT (RFC1918, 100.64.0.0/10) — см. ml-balancer-ingress-private.ipBlock.

  Первое ingress-правило (podSelector app=gateway) в спецификации остаётся для совместимости с локальными
  тестовыми средами; при разнесении по двум кластерам к ml-балансеру действует второе правило (ipBlock).


Порядок раскладки и команды Kustomize
--------------------------------------

  1) Кластер B (ML):

     kubectl kustomize --load-restrictor=LoadRestrictionsNone deploy/k8s/clusters/ml | kubectl apply -f -

  2) Пропишите доступное из кластера A DNS-имя на ml-balancer (LB / внутренняя зона).

  3) Кластер A (edge):

     kubectl kustomize --load-restrictor=LoadRestrictionsNone deploy/k8s/clusters/edge | kubectl apply -f -

Kustomize по умолчанию не тянет ../.. без --load-restrictor=LoadRestrictionsNone (или аналога в конфиг).


GPU / топология и опционально mTLS между кластерами
---------------------------------------------------
  deploy/k8s/overlays/cpu-gpu-topology — подпапки ml/ и edge/ (применять в каждом кластере свой kustomize).
  deploy/k8s/overlays/gpu-pool-rtx5000-a100 — то же, разнесение классов GPU.

HTTP/2 (TLS) и mTLS между edge и ML (опционально, даже во внутреннем контуре):
  см. deploy/k8s/overlays/intercluster-h2-mtls/README.txt и подборки kubectl из этого файла.

Отдельные LoadBalancer вместо внутрикластерной схемы (редко, для отладки):
  deploy/k8s/overlays/direct-pool-lb/ml и deploy/k8s/overlays/direct-pool-lb/edge.

Требуется CNI с поддержкой NetworkPolicy (Calico, Cilium, AWS VPC CNI + NP и т.д.). Иначе правила не
действуют — дублируйте ограничения security groups / firewall. Если источники трафика к ml-balancer
находятся в нестандартном CIDR, добавьте ipBlock в политику ml-balancer-ingress-private.

Meta: CI
--------
  workflow .github/workflows/deploy-k8s.yml уже применяет сначала clusters/ml, затем clusters/edge
  с разными секретами kubeconfig.
