# NFS cho Kubernetes test

Helm release: erp-nfs. Namespace: storage.
Chart: nfs-ganesha/nfs-server-provisioner, version 1.8.0.

server-values.yaml lưu cấu hình Helm của NFS server.
claims.json lưu hai PVC RWX, được tạo riêng trước khi triển khai ERP.
Chart ERP tham chiếu hai PVC này qua persistence.existingClaim.
