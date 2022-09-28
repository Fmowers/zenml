output "zenml_server_url" {
  value = var.create_ingress_controller? "https://${data.kubernetes_service.ingress-controller.status.0.load_balancer.0.ingress.0.hostname}/${var.ingress_path}/" : "https://${var.ingress_controller_hostname}/${var.ingress_path}/"
}

output "tls_crt" {
  value = base64decode(data.kubernetes_secret.certificates.binary_data["tls.crt"])
  sensitive = true
}
output "tls_key" {
  value = base64decode(data.kubernetes_secret.certificates.binary_data["tls.key"])
  sensitive = true
}
output "ca_crt" {
  value = base64decode(data.kubernetes_secret.certificates.binary_data["ca.crt"])
  sensitive = true
}