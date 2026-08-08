# LEGACY — FAISS Study Notes

> **Status**: LEGACY. Original: `reports/FAISS Document.docx` (converted
> 2026-08-08). Informal study notes written while learning face encoders and
> FAISS at the idea stage. The examples use `face_recognition`'s 128-d
> embeddings; the **actual system** uses InsightFace `buffalo_l` (SCRFD +
> ArcFace) with 512-d normalized embeddings and FAISS `IndexFlatIP` — see
> `../ARCHITECTURE.md` and `../plans/RECOGNITION_OPTIMIZATION_PLAN.md`.
> Kept only as context showing the original inspiration.

---

FAISS là cái gì?

Những bức ảnh vốn đã là những con số. Thật vậy, đối với máy tính thì nó là cả 1 ma trận pixel.

Ví dụ đơn giản, một bức ảnh cỡ 150x150 pixel thì đã có tới tận 67.500 giá trị của các block pixel.

Vấn đề đặt ra ở đây: So sánh trực tiếp giữa các pixel không hiệu quả. Do đó, ta cần 1 mô hình AI rút ra những đặc điểm ổn định hơn pixel.

Facebook AI Similarity Search (FAISS) là một thư viện dùng để tìm kiếm các vector giống nhau nhất trong một tập vector lớn.

FAISS không trực tiếp nhìn cái ảnh đó, mà nó sẽ làm việc với các dãy số. Nó phân tích ảnh được feed vào thành vector có 128 phần tử.

## FAISS hoạt động như thế nào?

Vậy thứ biến ảnh thành vector là cái gì? —> Face Encoder

Đây là hàm đó:

```python
face_recognition.face_encodings(image)
```

Phía sau hàm này là cả 1 mạng neural đã được huấn luyện, gồm: Face encoder, Face embedding model, feature extractor.

Nó nhận ảnh khuôn mặt và trả về vector 1 chiều có 128 số —> FACE EMBEDDING ("Dấu vân tay toán học" đại diện cho khuôn mặt)

Vậy tại sao chỉ lấy có 128 giá trị vậy??? Tại vì pick random, nhưng mà nó cân bằng: Đủ lớn để chứa thông tin khuôn mặt, đủ nhỏ để lưu trữ và tìm kiếm nhanh và không quá nặng khi có nhiều người trong database.

> NOTE: Database dùng model nào → ảnh truy vấn cũng phải dùng đúng model đó.

Oke và đây là cách hoạt động chính của nó:

Face Encoder: Nếu cùng 1 người thì các chỉ số của dãy vector 128 giá trị đó sẽ nằm gần nhau. Còn khác thì các chỉ số sẽ nằm khác xa nhau.

Nghe khó hiểu, nhưng dưới đây là ví dụ minh họa 2 chiều:

- Ảnh Tien 1 → [1.0, 1.1]
- Ảnh Tien 2 → [1.2, 0.9]
- Ảnh Tien 3 → [0.9, 1.0]

Ta thấy một điểm chung trong ảnh Tiến là → Các ảnh của Tiến sẽ tập trung loanh quanh giá trị [1, 1]

Giờ cái camera mới chụp được ảnh Tiến, đem vào so sánh thấy ảnh camera chụp ở vị trí [1.1, 1.2]

—> Gần giá trị trung bình của Tiến, giống Tiến → Oke Đó là Tiến

Trường hợp khác thì ngược lại, giá trị xa thì khác thui.

Trong hệ thống thật thì có 128 tọa độ chứ không hẳn đơn giản như trên đâu, minh họa thôi.

Về vấn đề model thì có model được huấn luyện sẵn rồi. Model có thể lấy dùng là InsightFace. Model buffalo_l.

*(Hệ thống thực tế đúng là dùng InsightFace buffalo_l — nhưng embedding 512-d, xem `../ARCHITECTURE.md`.)*

Vậy bên trong cái Encoder có chuyện gì xảy ra:

Ảnh khuôn mặt → Chuẩn hóa kích thước ảnh → Các lớp convolution tìm đặc trưng đơn giản → Các lớp sâu hơn kết hợp các đặc trưng đó lại, thành những mẫu phức tạp hơn → Nén thành 128 số.

OKE SAU KHI FACE ENCODER TẠO VECTOR THÌ FAISS MỚI VÀO VIỆC NHA

Giả sử db có:

- Tien → vector T
- An → vector A
- Binh → vector B

Khi camera nhìn thấy 1 khuôn mặt:

```
Ảnh camera
    ↓ Face Encoder
Vector Q
```

FAISS tính xem vector Q gần vector nào nhất:

- distance(Q, Tien) = 0.18
- distance(Q, An) = 0.84
- distance(Q, Binh) = 0.96

Kết quả lòi ra là Vector gần nhất là Tiến —> Giống Tiến nhất

Sau đó nó sẽ kiểm tra threshold, nếu khoảng cách đủ nhỏ thì kết luận. Còn không thì Unknown, chịu chết.

> NOTE:
> - Face Encoder trả lời: "Khuôn mặt này được biểu diễn bằng vector nào?"
> - FAISS trả lời: "Vector này gần vector nào nhất trong database?"

Đơn giản hóa: Có 3 phase. Đầu tiên sẽ detect xem khuôn mặt nằm đâu trong ảnh (Face Detection) → Chuyển khuôn mặt thành 128 con số (Face Encoder) → Tìm vector gần nhất trong database (FAISS).
