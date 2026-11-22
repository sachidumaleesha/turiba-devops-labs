resource "kind_cluster" "course" {
  name           = var.cluster_name
  wait_for_ready = true
}

resource "kubernetes_namespace_v1" "course" {
  metadata {
    name = "course"
  }
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "kubernetes_secret_v1" "db" {
  metadata {
    name      = "db-secret"
    namespace = kubernetes_namespace_v1.course.metadata[0].name
  }

  data = {
    password = random_password.db.result
  }
}

resource "helm_release" "course_app" {
  name      = "course-app"
  namespace = "courses"
  chart     = "${path.module}/../chart/course-app"

  set = [
    {
      name  = "api.replicas"
      value = tostring(var.api_replicas)
    },
  ]

  depends_on = [kubernetes_secret_v1.db]
}
