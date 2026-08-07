import React from 'react'
import SearchProduct from './components/SearchProduct'
import ChatBot from './components/ChatBot'

function App() {
  return (
    <div className="app">
      {/* ===== HERO ===== */}
      <header className="app-header">
        <div className="header-content">
          <div className="hero-badge">
            <span className="hero-badge-dot"></span>
            So sánh giá thông minh từ các cửa hàng công nghệ uy tín
          </div>
          <h1>
            Tìm <span className="hero-title-gradient">Giá Tốt Nhất</span>
            <br />
            Cho Sản Phẩm Công Nghệ
          </h1>
          <p className="subtitle">
            Nhập tên sản phẩm, chúng tôi quét giá từ FPT Shop, Thế Giới Di Động,
            CellphoneS... và trả về top 3 mức giá rẻ nhất — kèm dự báo xu hướng
            giá bằng AI (LSTM)
          </p>

          <div className="hero-stats">
            <div className="hero-stat">
              <span className="hero-stat-value">Top 3</span>
              <span className="hero-stat-label">Giá rẻ nhất</span>
            </div>
            <div className="hero-stat">
              <span className="hero-stat-value">3.000+</span>
              <span className="hero-stat-label">Sản phẩm theo dõi</span>
            </div>
            <div className="hero-stat">
              <span className="hero-stat-value">24/7</span>
              <span className="hero-stat-label">Cập nhật giá tự động</span>
            </div>
            <div className="hero-stat">
              <span className="hero-stat-value">AI</span>
              <span className="hero-stat-label">Dự báo giá LSTM</span>
            </div>
          </div>
        </div>
      </header>

      <main>
        <SearchProduct />

        {/* ===== FEATURES ===== */}
        <section className="features-section">
          <h2 className="features-title">Vì sao chọn chúng tôi?</h2>
          <p className="features-sub">
            Toàn bộ tính năng được thiết kế để bạn mua sắm thông minh hơn
          </p>
          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-icon">⚡</div>
              <h3>Top 3 giá rẻ nhất</h3>
              <p>
                Tìm kiếm 1 từ khoá, trả về 3 mức giá rẻ nhất khớp với sản phẩm —
                so sánh nhanh và chính xác, không cần mở từng trang web.
              </p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">📈</div>
              <h3>Dự báo giá bằng AI</h3>
              <p>
                Mô hình LSTM phân tích lịch sử giá 30-90 ngày để dự báo xu
                hướng giá 7 ngày tới, giúp bạn chọn thời điểm mua tốt nhất.
              </p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🤖</div>
              <h3>Trợ lý mua sắm thông minh</h3>
              <p>
                Chat với AI để được gợi ý sản phẩm theo ngân sách, nhu cầu và
                nhận tư vấn giá tốt nhất ngay trong trang.
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* ===== FOOTER ===== */}
      <footer className="app-footer">
        <div className="footer-content">
          <div className="footer-brand">
            <h3>🔍 So Sánh Giá Sản Phẩm</h3>
            <p>
              Nền tảng so sánh giá và dự báo xu hướng cho sản phẩm công nghệ.
              Dữ liệu được thu thập tự động từ các trang thương mại điện tử
              đối tác và cập nhật liên tục.
            </p>
          </div>
          <div className="footer-col">
            <h4>Cửa hàng đối tác</h4>
            <ul>
              <li>🛒 FPT Shop</li>
              <li>📱 Thế Giới Di Động</li>
              <li>📞 CellphoneS</li>
              <li>🏪 Hoàng Hà Mobile</li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Tính năng</h4>
            <ul>
              <li>⚡ Top 3 giá rẻ nhất</li>
              <li>📈 Dự báo giá LSTM</li>
              <li>🤖 Trợ lý mua sắm AI</li>
              <li>💬 Tư vấn sản phẩm</li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          © {new Date().getFullYear()} So Sánh Giá Sản Phẩm — Dữ liệu mang tính
          tham khảo, giá có thể thay đổi theo thời điểm.
        </div>
      </footer>

      {/* ChatBot floating button */}
      <ChatBot />
    </div>
  )
}

export default App