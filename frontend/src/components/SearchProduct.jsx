import React, { useState, useRef } from 'react';
import PriceChart from './PriceChart';

// Danh sách 7 sàn cố định
const STORES = [
  { key: 'fpt', name: 'FPT Shop', icon: '🛒' },
  { key: 'tgdd', name: 'Thế Giới Di Động', icon: '📱' },
  { key: 'cellphones', name: 'CellphoneS', icon: '📞' },
  { key: 'hoangha', name: 'Hoàng Hà Mobile', icon: '🏪' },
  { key: 'didongviet', name: 'Di Động Việt', icon: '🇻🇳' },
  { key: 'viettel', name: 'Viettel Store', icon: '📶' },
  { key: 'clickbuy', name: 'Clickbuy', icon: '🛍️' },
];

// Map source name -> store key để nhóm sản phẩm
const SOURCE_TO_KEY = {
  'FPT Shop': 'fpt',
  'Thế Giới Di Động': 'tgdd',
  'CellphoneS': 'cellphones',
  'Hoàng Hà Mobile': 'hoangha',
  'Di Động Việt': 'didongviet',
  'Viettel Store': 'viettel',
  'Clickbuy': 'clickbuy',
};

// Màu sắc cho từng sàn
const STORE_COLORS = {
  fpt: '#e74c3c',
  tgdd: '#2ecc71',
  cellphones: '#3498db',
  hoangha: '#9b59b6',
  didongviet: '#e67e22',
  viettel: '#1abc9c',
  clickbuy: '#34495e',
};

export default function SearchProduct() {
  const [keyword, setKeyword] = useState('');
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [storeStatus, setStoreStatus] = useState({});
  const [cached, setCached] = useState(false);
  const eventSourceRef = useRef(null);

  // Nhóm sản phẩm theo source
  const groupedProducts = {};
  STORES.forEach(store => {
    groupedProducts[store.key] = [];
  });
  
  products.forEach(prod => {
    const key = SOURCE_TO_KEY[prod.source] || null;
    if (key && groupedProducts[key]) {
      groupedProducts[key].push(prod);
    }
  });

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

    // Set tất cả store về trạng thái "loading"
    const initialStatus = {};
    STORES.forEach(store => { initialStatus[store.key] = 'loading'; });
    setStoreStatus(initialStatus);

    // Tạo EventSource đến SSE endpoint
    const url = `http://localhost:8000/api/search/stream?q=${encodeURIComponent(query)}${forceRefresh ? '&force_refresh=true' : ''}`;
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    // Event: cached — dữ liệu có sẵn trong DB, trả về tất cả cùng lúc
    eventSource.addEventListener('cached', (event) => {
      try {
        const data = JSON.parse(event.data);
        const cachedProducts = data.products || [];
        setProducts(cachedProducts);
        setCached(true);

        // Cập nhật trạng thái từng sàn
        const newStatus = {};
        STORES.forEach(store => {
          const hasProducts = cachedProducts.some(p => SOURCE_TO_KEY[p.source] === store.key);
          newStatus[store.key] = hasProducts ? 'done' : 'empty';
        });
        setStoreStatus(newStatus);
      } catch (err) {
        console.error("Lỗi parse cached event:", err);
      }
    });

    // Event: store — một sàn vừa scrape xong, push products ngay lập tức
    eventSource.addEventListener('store', (event) => {
      try {
        const data = JSON.parse(event.data);
        const sourceName = data.source;
        const storeKey = SOURCE_TO_KEY[sourceName];

        if (data.products && data.products.length > 0) {
          // Append sản phẩm mới vào danh sách (render ngay lập tức)
          setProducts(prev => [...prev, ...data.products]);
        }

        // Cập nhật trạng thái sàn này → done hoặc empty
        if (storeKey) {
          setStoreStatus(prev => ({
            ...prev,
            [storeKey]: data.count > 0 ? 'done' : 'empty',
          }));
        }
      } catch (err) {
        console.error("Lỗi parse store event:", err);
      }
    });

    // Event: done — tất cả sàn đã xong, backend đã lưu DB
    eventSource.addEventListener('done', (event) => {
      try {
        const data = JSON.parse(event.data);
        setLoading(false);
        setCached(data.cached || false);

        // Đánh dấu các sàn vẫn còn "loading" là "empty" (không có dữ liệu)
        setStoreStatus(prev => {
          const newStatus = { ...prev };
          Object.keys(newStatus).forEach(key => {
            if (newStatus[key] === 'loading') {
              newStatus[key] = 'empty';
            }
          });
          return newStatus;
        });
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
      // Chỉ báo lỗi nếu chưa nhận được event nào (đang loading)
      setLoading(prevLoading => {
        if (prevLoading) {
          setError("Không thể kết nối đến máy chủ hoặc có lỗi xảy ra.");
          const errorStatus = {};
          STORES.forEach(store => { errorStatus[store.key] = 'error'; });
          setStoreStatus(errorStatus);
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

  // Render sản phẩm trong một cột
  const renderStoreColumn = (store) => {
    const storeProducts = groupedProducts[store.key] || [];
    const status = storeStatus[store.key];
    const color = STORE_COLORS[store.key];

    return (
      <div key={store.key} className="store-column">
        {/* Header cột */}
        <div className="store-column-header" style={{ borderBottomColor: color }}>
          <div className="store-column-header-top">
            <span className="store-icon">{store.icon}</span>
            <span className="store-name">{store.name}</span>
            {status === 'loading' && <span className="store-status-badge loading-badge">Đang tìm</span>}
            {status === 'done' && <span className="store-status-badge done-badge">✓ {storeProducts.length} SP</span>}
            {status === 'empty' && <span className="store-status-badge empty-badge">0 SP</span>}
            {status === 'error' && <span className="store-status-badge error-badge">⚠ Lỗi</span>}
            {!status && <span className="store-status-badge idle-badge">⏳ Chờ</span>}
          </div>
        </div>

        {/* Danh sách sản phẩm trong cột */}
        <div className="store-column-body">
          {status === 'loading' && (
            <div className="column-loading">
              <div className="column-spinner" style={{ borderTopColor: color }}></div>
              <span>Đang tìm kiếm...</span>
            </div>
          )}
          
          {status === 'empty' && (
            <div className="column-empty">
              <span className="column-empty-icon">🔍</span>
              <span>Không tìm thấy sản phẩm</span>
            </div>
          )}

          {status === 'error' && (
            <div className="column-empty">
              <span className="column-empty-icon">⚠️</span>
              <span>Lỗi kết nối</span>
            </div>
          )}

          {(status === 'done' || !status) && storeProducts.length === 0 && status !== 'loading' && status !== 'empty' && status !== 'error' && (
            <div className="column-empty">
              <span className="column-empty-icon">⏳</span>
              <span>Chờ tìm kiếm...</span>
            </div>
          )}

          {storeProducts.map((prod, index) => (
            <div key={index} className="column-product-card">
              <div className="column-product-image-wrapper">
                <img 
                  src={prod.image_url || 'https://via.placeholder.com/150'} 
                  alt={prod.name} 
                  className="column-product-image"
                  onError={(e) => { e.target.src = 'https://via.placeholder.com/150'; }}
                />
              </div>
              <div className="column-product-info">
                <h4 className="column-product-name" title={prod.name}>{prod.name}</h4>
                <p className="column-product-price">{prod.price}</p>
                <a 
                  href={prod.product_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="column-product-link"
                  style={{ backgroundColor: color }}
                >
                  Xem chi tiết →
                </a>
                {/* Biểu đồ LSTM inline - tự động hiển thị */}
                <PriceChart product={prod} />
              </div>
            </div>
          ))}
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
      </div>

      {/* Hiển thị lỗi */}
      {error && (
        <div className="error-container">
          <span className="error-icon">⚠️</span>
          <p>{error}</p>
          <p className="error-hint">Hãy đảm bảo backend đang chạy ở http://localhost:8000</p>
        </div>
      )}

      {/* Badge cache + nút scrape lại */}
      {products.length > 0 && (
        <div className="cache-bar">
          {cached ? (
            <span className="cache-badge cached">⚡ Dữ liệu từ DB (trả về ngay)</span>
          ) : (
            <span className="cache-badge fresh">🔄 Vừa scrape mới</span>
          )}
          <button
            className="refresh-btn"
            onClick={() => handleForceRefresh()}
            disabled={loading}
            title="Scrape lại từ 7 sàn (bỏ qua cache)"
          >
            {loading ? 'Đang scrape...' : '🔄 Scrape lại'}
          </button>
        </div>
      )}

      {/* 7 cột cho 7 sàn */}
      <div className="stores-grid">
        {STORES.map(store => renderStoreColumn(store))}
      </div>
    </div>
  );
}
