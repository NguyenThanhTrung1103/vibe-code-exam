# Hướng dẫn — chặn IP non-VN truy cập `blog-trungnt.anhanh.work`

**Mục tiêu:** chỉ cho phép truy cập từ IP Việt Nam tới blog. Dùng Cloudflare WAF
Custom Rule (Free plan, không cần Zero Trust, không cần thẻ).

**Domain:** `anhanh.work` &nbsp;·&nbsp; **Hostname:** `blog-trungnt.anhanh.work`

---

## Bước 1 — Mở trang Custom Rules

Bấm trực tiếp link này (đã có account_id sẵn):

```
https://dash.cloudflare.com/c60db492217e2c9080fd42cae59e0fe4/anhanh.work/security/security-rules?type=http_request_firewall_custom
```

Trang này có heading **`Security rules`**, tab **`Security rules`** đang active,
filter dropdown bên trái là **`Custom rules`**.

---

## Bước 2 — Tạo rule mới

1. Bấm nút xanh **`+ Create rule`** ở góc trên-phải.
2. Dropdown bung ra → chọn **`Custom rules`** (mục đầu tiên).
3. URL chuyển sang `…/security/security-rules/custom-rules/create` — đây là form
   `New custom rule`.

---

## Bước 3 — Điền form

### 3.1 — Rule name

```
Block non-VN to blog-trungnt
```

### 3.2 — Expression (chế độ raw)

Bấm link **`Use expression builder`** ở góc phải để toggle giữa visual builder và
raw text. Nếu textarea raw đang hiện thì để nguyên. Dán đoạn này:

```
(http.host eq "blog-trungnt.anhanh.work" and ip.geoip.country ne "VN")
```

> Logic: chặn request có Host = `blog-trungnt.anhanh.work` **VÀ** IP source country
> không phải `VN` (mã ISO Việt Nam).

### 3.3 — Action

Phần **`Then take action…`** → dropdown **`Choose action`** đang là `Select…`:

1. Click vào dropdown.
2. Chọn **`Block`** (option đầu tiên trong list).

> Đừng chọn `Managed Challenge` hay `JS Challenge` — bạn muốn chặn cứng, không
> muốn cho người ngoài VN solve CAPTCHA để vào.

---

## Bước 4 — Deploy

Bấm nút xanh **`Deploy`** ở góc phải-dưới.

> Nếu chưa chắc chắn, có thể bấm **`Save as Draft`** trước, review lại, rồi quay
> lại deploy sau. Draft = rule tồn tại nhưng KHÔNG chặn traffic.

Sau khi deploy:
- URL chuyển về list `…/security/security-rules?type=http_request_firewall_custom`
- Rule mới hiện ở đầu danh sách, status **`Active`**, counter `0/5 used` → `1/5 used`.

---

## Bước 5 — Verify

### Từ máy Việt Nam

```
Mở browser: https://blog-trungnt.anhanh.work
→ render blog bình thường (như cũ)
```

### Từ VPN nước ngoài (US/SG/JP)

```bash
curl -I -A "Mozilla/5.0" https://blog-trungnt.anhanh.work
# Expected:
#   HTTP/2 403
#   server: cloudflare
#   cf-mitigated: challenge      <-- header này xác nhận WAF đã chặn
```

Trên trình duyệt sẽ thấy trang Cloudflare với title `Sorry, you have been blocked`
hoặc tương tự, footer ghi `Ray ID: …`.

### Xem log block trên dashboard

`Security → Events` (cùng zone `anhanh.work`) → filter `Action = block`,
`Service = WAF`. Mỗi block hiện 1 row với IP nguồn + country.

---

## Lỗi hay gặp

| Triệu chứng | Nguyên nhân | Fix |
|---|---|---|
| Rule đã deploy nhưng từ VN cũng bị chặn | Bạn dùng VPN/proxy ra US khi test | Tắt VPN, test lại từ IP Việt thật |
| Từ nước ngoài vẫn vào được | `http.host` viết sai (vd `BLOG-trungnt`) | So lại chính xác `blog-trungnt.anhanh.work`, lower-case |
| Block luôn cả các subdomain khác | Bạn quên hostname trong expression | Đảm bảo có `http.host eq "..."`, không chỉ có `ip.geoip.country` |
| `Deploy` button xám không bấm được | Form còn missing field | Action đang `Select…` — phải chọn `Block` mới enable Deploy |

---

## Mở rộng (tùy chọn)

### Thêm allowlist IP riêng (vd IP cố định khi đi nước ngoài)

Sửa expression:

```
(http.host eq "blog-trungnt.anhanh.work"
  and ip.geoip.country ne "VN"
  and ip.src ne 203.0.113.42)
```

Thay `203.0.113.42` bằng IP công cộng của bạn. Lưu rule lại.

### Thêm whitelist nhiều nước

```
(http.host eq "blog-trungnt.anhanh.work"
  and not (ip.geoip.country in {"VN" "SG" "JP"}))
```

---

## Rollback

Nếu cần tắt:
- Vào lại trang Custom Rules → toggle rule sang **`Off`** (giữ rule, ngừng enforce).
- Hoặc xoá hẳn: 3-dot menu cuối row → `Delete`.
