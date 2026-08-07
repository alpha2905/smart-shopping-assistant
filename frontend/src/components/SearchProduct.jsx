import React, { useState, useRef } from 'react';
import PriceChart from './PriceChart';
import SentimentPanel from './SentimentPanel';

// Backend URL (Vite proxy có thể không hoạt động nếu chạy port khác 3000)
const API_BASE = 'http://localhost:8000';

// Màu sắc cho từng sàn
const STORE_COLORS = {
  'FPT Shop': '#e74c3c',
  'Thế Giới Di Động': '#2ecc71',
  'CellphoneS': '#3498db',
  'Hoàng Hà Mobile': '#9b59b6',
  'Di Động Việt': '#e67e22',
  'Viettel Store': '#1abc9c',
  'Clickbuy': '#34495e',
  'MobileCity': '#f39c12',
};

const STORE_ICONS = {
  'FPT Shop': '🛒',
  'Thế Giới Di Động': '📱',
  'CellphoneS': '📞',
  'Hoàng Hà Mobile': '🏪',
  'Di Động Việt': '🇻🇳',
  'Viettel Store': '📶',
  'Clickbuy': '🛍️',
  'MobileCity': '🏙️',
};

function formatPrice(priceStr) {
  if (!priceStr) return 'Liên hệ';
  // Giữ nguyên chuỗi giá gốc nhưng bỏ ký tự không cần thiết
  return priceStr.trim();
}

function getStoreColor(source) {
  return STORE_COLORS[source] || '#6366f1';
}

function getStoreIcon(source) {
  return STORE_ICONS[source] || '🏷️';
}

export default function SearchProduct() {
  const [keyword, setKeyword] = useState('');
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [cached, setCached] = useState(false);
  const eventSourceRef = useRef(null);

  // Hàm chung: gọi SSE endpoint, nhận kết quả từng sàn streaming
  const searchWithSSE = (query, forceRefresh = false) => {
    // Đóng EventSource cũ nếu còn đang mở
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setLoading(true);
    setError(null);
    setProducts([]);
    setCached(false);

    // Tạo EventSource đến SSE endpoint trực tiếp trên backend :8000
    const url = `${API_BASE}/api/search/stream?q=${encodeURIComponent(query)}${forceRefresh ? '&force_refresh=true' : ''}`;
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    // Event: cached — dữ liệu có sẵn trong DB, trả về top 3 đã lọc
    eventSource.addEventListener('cached', (event) => {
      try {
        const data = JSON.parse(event.data);
        const cachedProducts = data.products || [];
        setProducts(cachedProducts);
        setCached(true);
        setLoading(false);
      } catch (err) {
        console.error("Lỗi parse cached event:", err);
      }
    });

    // Event: store — một sàn vừa scrape xong (chỉ log tiến trình,
    // kết quả cuối lấy từ done event đã filter top 3)
    eventSource.addEventListener('store', (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log(`Đã xong sàn: ${data.source} (${data.count || 0} sản phẩm)`);
      } catch (err) {
        console.error("Lỗi parse store event:", err);
      }
    });

    // Event: done — tất cả sàn đã xong, backend gửi top 3 giá rẻ nhất
    eventSource.addEventListener('done', (event) => {
      try {
        const data = JSON.parse(event.data);
        setLoading(false);
        setCached(data.cached || false);
        if (data.products && Array.isArray(data.products)) {
          setProducts(data.products);
        }
      } catch (err) {
        console.error("Lỗi parse done event:", err);
      }
      eventSource.close();
      eventSourceRef.current = null;
    });

    // Event: error — lỗi từ backend
    eventSource.addEventListener('error', (event) => {
      console.error("SSE error:", event);
    });

    // EventSource onerror — lỗi kết nối (network, server down)
    eventSource.onerror = () => {
      setLoading(prevLoading => {
        if (prevLoading) {
          setError("Không thể kết nối đến máy chủ hoặc có lỗi xảy ra.");
        }
        return false;
      });
      eventSource.close();
      eventSourceRef.current = null;
    };
  };

  const handleForceRefresh = (e) => {
    if (e) e.preventDefault();
    if (!keyword.trim()) return;
    searchWithSSE(keyword, true);
  };

  const handleSearch = (e) => {
    e.preventDefault();
    if (!keyword.trim()) return;
    searchWithSSE(keyword, false);
  };

  // Render 1 card sản phẩm
  const renderProductCard = (prod, index) => {
    const color = getStoreColor(prod.source);
    const icon = getStoreIcon(prod.source);
    const isCheapest = index === 0 && products.length > 0;
    const isSecond = index === 1;

    return (
      <div key={prod.product_url + index} className={`product-card ${isCheapest ? 'product-card-best' : ''}`}>
        {/* Badge rẻ nhất */}
        {isCheapest && (
          <div className="best-price-badge">💎 Giá tốt nhất</div>
        )}
        {isSecond && (
          <div className="second-price-badge">⭐ Nên cân nhắc</div>
        )}

        <div className="product-card-image-wrapper">
          <img
            src={prod.image_url || 'https://via.placeholder.com/400x400?text=Sản+phẩm'}
            alt={prod.name}
            className="product-card-image"
            onError={(e) => { e.target.src = 'https://via.placeholder.com/400x400?text=Sản+phẩm'; }}
          />
        </div>

        <div className="product-card-body">
          <div className="product-card-store-row">
            <span className="product-card-store-badge" style={{ backgroundColor: color + '1a', color: color, borderColor: color + '40' }}>
              {icon} {prod.source || 'Cửa hàng'}
            </span>
          </div>

          <h3 className="product-card-name" title={prod.name}>{prod.name}</h3>

          <div className="product-card-price-row">
            <span className="product-card-price">{formatPrice(prod.price)}</span>
            {prod.price_numeric > 0 && (
              <span className="product-card-saleprice">đ</span>
            )}
          </div>

          {/* Gợi ý từ AI dựa trên vị trí giá */}
          {prod.price_numeric > 0 && (
            <div className="product-card-ai-tip">
              {index === 0
                ? <span>💡 <b>Rẻ nhất</b> trên các sàn đang so sánh</span>
                : index === 1
                  ? <span>💡 Giá cạnh tranh thứ 2</span>
                  : <span>💡 Cân nhắc so với các lựa chọn khác</span>
              }
            </div>
          )}

          {prod.comments && prod.comments.length > 0 && (
            <div className="product-card-rating">
              <span className="rating-stars">👍</span>
              <span className="rating-count">{prod.comments.length} đánh giá</span>
            </div>
          )}

          <a
            href={prod.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className="product-card-link"
            style={{ backgroundColor: color }}
          >
            Xem chi tiết →
          </a>

          {/* Biểu đồ LSTM inline - tự động hiển thị */}
          <PriceChart product={prod} />

          {/* Phân tích cảm xúc bình luận bằng PhoBERT */}
          <SentimentPanel product={prod} />
        </div>
      </div>
    );
  };

  return (
    <div className="container">
      <div className="search-section">
        {/* Form tìm kiếm */}
        <form onSubmit={handleSearch} className="search-form">
          <div className="search-box">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="Nhập tên sản phẩm (Ví dụ: iPhone 17, Samsung Galaxy)..."
              className="search-input"
            />
            <button type="submit" className="search-button" disabled={loading}>
              {loading ? 'Đang tìm...' : 'Tìm kiếm'}
            </button>
          </div>
        </form>

        {/* Gợi ý tìm kiếm nhanh khi chưa tìm */}
        {!loading && products.length === 0 && !error && (
          <div className="search-hint">
            <span>Phổ biến:</span>
            <div className="search-hint-suggestions">
              {['iPhone 17', 'Samsung Galaxy', 'Laptop Dell', 'MacBook'].map((s) => (
                <button
                  key={s}
                  type="button"
                  className="suggestion-chip"
                  onClick={() => {
                    setKeyword(s);
                    searchWithSSE(s, false);
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Hiển thị lỗi */}
      {error && (
        <div className="error-container">
          <span className="error-icon">⚠️</span>
          <p>{error}</p>
          <p className="error-hint">Hãy đảm bảo backend đang chạy để có thể tìm kiếm sản phẩm.</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <span>Đang quét {7} cửa hàng để tìm top 3 giá tốt nhất...</span>
        </div>
      )}

      {/* Badge cache + nút scrape lại */}
      {!loading && products.length > 0 && (
        <div className="cache-bar">
          {cached ? (
            <span className="cache-badge cached">⚡ Dữ liệu từ DB (trả về ngay)</span>
          ) : (
            <span className="cache-badge fresh">🔄 Vừa scrape mới</span>
          )}
          <button
            className="refresh-btn"
            onClick={() => handleForceRefresh()}
            title="Scrape lại từ 7 sàn (bỏ qua cache)"
          >
            🔄 Scrape lại
          </button>
        </div>
      )}

      {/* Chỉ hiển thị kết quả khi đã xong và có sản phẩm */}
      {!loading && products.length > 0 && (
        <div className="results-header">
          <h2>Kết quả tìm kiếm</h2>
          <p>
            Top {Math.min(products.length, 3)} sản phẩm khớp với "{keyword}" — 
            sắp xếp theo giá rẻ nhất
          </p>
        </div>
      )}

      {/* Grid 3 card sản phẩm */}
      {!loading && products.length > 0 && (
        <div className="products-grid">
          {products.slice(0, 3).map((prod, index) => renderProductCard(prod, index))}
        </div>
      )}

      {/* Không có kết quả */}
      {!loading && products.length === 0 && !error && (
        <div className="no-results">
          <span className="no-results-icon">🔍</span>
          <h3>Chưa có kết quả</h3>
          <p>Hãy thử tìm kiếm một sản phẩm công nghệ để xem giá tốt nhất từ các sàn.</p>
        </div>
      )}
    </div>
  );
}