resource "kind_cluster" "course" {
  name           = var.cluster_name
  wait_for_ready = true
}
