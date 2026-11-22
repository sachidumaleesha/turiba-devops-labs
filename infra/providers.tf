provider "kind" {}

provider "kubernetes" {
  host                   = kind_cluster.course.endpoint
  client_certificate     = kind_cluster.course.client_certificate
  client_key             = kind_cluster.course.client_key
  cluster_ca_certificate = kind_cluster.course.cluster_ca_certificate
}

provider "helm" {
  kubernetes = {
    host                   = kind_cluster.course.endpoint
    client_certificate     = kind_cluster.course.client_certificate
    client_key             = kind_cluster.course.client_key
    cluster_ca_certificate = kind_cluster.course.cluster_ca_certificate
  }
}
