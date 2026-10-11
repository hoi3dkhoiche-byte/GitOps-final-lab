# Sealed Secrets — metasfresh ERP

## 1. Nguyên tắc quản lý

Hệ thống sử dụng Bitnami Sealed Secrets để lưu trữ thông tin cấu hình nhạy cảm trong GitOps dưới dạng đã mã hóa.

- Không commit Kubernetes Secret dạng plaintext.
- Không lưu mật khẩu trong README, Helm values hoặc source code.
- SealedSecret được mã hóa với đúng controller, namespace và Secret name.
- Quá trình cập nhật credentials phải được kiểm tra và phê duyệt trước khi đồng bộ.

## 2. Danh sách Secrets

| Secret | Chức năng | Trạng thái |
|---|---|---|
| `erp-properties` | Cấu hình metasfresh Core/API, gồm kết nối PostgreSQL | Đang sử dụng |
| `erp-rabbit-secret` | Credentials RabbitMQ | Đang sử dụng |
| `harbor-pull` | Credentials pull container images từ Harbor | Đang sử dụng |
| `erp-postgres-ca` | CA certificate phục vụ xác thực TLS PostgreSQL | Tồn tại trong cluster, cần xác minh cấu hình sử dụng và nguồn quản lý |
| `erp-origin-tls` | TLS certificate cho origin Ingress nếu kiến trúc TLS yêu cầu | Chưa xác nhận cần tạo |
| `erp-db-secret` | Secret DB riêng trong tài liệu cũ | Chưa có consumer trong Helm chart hiện tại |

## 3. GitOps configuration

Repository: `GitOps-final-lab`

Application: `metasfresh-erp-secrets`

Manifest directory: `sealed-secrets/`

Source Application: `platform/argocd/application-secrets.yaml`

Bootstrap generator: `platform/bootstrap.py`

Không chỉnh sửa generated artifacts làm nguồn cấu hình chính.

## 4. Sealed Secrets Controller

Namespace: `sealed-secrets`

Deployment: `sealed-secrets-controller`

Mặc định sử dụng strict scope, gắn với Secret name và namespace.

## 5. Quy trình cập nhật

1. Xác minh Secret hiện có và workload sử dụng.
2. Tạo SealedSecret bằng controller certificate hợp lệ.
3. Kiểm tra khả năng giải mã bằng `kubeseal --validate`.
4. Review manifest, diff và GitOps Application.
5. Commit và push qua quy trình đã phê duyệt.
6. Đồng bộ Application ở chế độ manual trong giai đoạn chuyển đổi.
7. Kiểm tra trạng thái SealedSecret, Secret và workload.
8. Xoay vòng credentials theo quy trình riêng và kiểm tra sau rotation.

Không tự động prune hoặc xóa Secrets khi chưa xác định ownership và ảnh hưởng tới ứng dụng.

## 6. Database

Metasfresh hiện sử dụng thuộc tính `Connection` trong `metasfresh.properties` để kết nối PostgreSQL.

Không tạo `erp-db-secret` riêng nếu chưa có workload sử dụng.

Các thay đổi về database cần được kiểm thử và phê duyệt trước khi cập nhật runtime Secret.
