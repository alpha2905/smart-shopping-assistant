import React, { useState } from 'react';
import axios from 'axios';
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

  const handleForceRefresh = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    setError(null);
    setProducts([]);
    const initialStatus = {};
    STORES.forEach(store => { initialStatus[store.key] = 'loading'; });
    setStoreStatus(initialStatus);

    try {
      const response = await axios.get(`http://localhost:8000/api/search?q=${encodeURIComponent(keyword)}&force_refresh=true`);
      const resultProducts = response.data.products || [];
      setProducts(resultProducts);
      setCached(false);
      const newStatus = {};
      STORES.forEach(store => {
        const hasProducts = resultProducts.some(p => SOURCE_TO_KEY[p.source] === store.key);
        newStatus[store.key] = hasProducts ? 'done' : 'empty';
      });
      setStoreStatus(newStatus);
    } catch (err) {
      console.error("Lỗi force refresh:", err);
      setError("Không thể scrape lại. Hãy thử lại.");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!keyword.trim()) return;

    setLoading(true);
    setError(null);
    
    // Reset products và set tất cả store về trạng thái "đang tìm"
    setProducts([]);
    const initialStatus = {};
    STORES.forEach(store => {
      initialStatus[store.key] = 'loading';
    });
    setStoreStatus(initialStatus);

    try {
      // Gọi API đến Backend FastAPI (chạy ở cổng 8000)
      const response = await axios.get(`http://localhost:8000/api/search?q=${encodeURIComponent(keyword)}`);
      const resultProducts = response.data.products || [];
      setProducts(resultProducts);
      setCached(response.data.cached || false);
      
      // Cập nhật trạng thái cho từng sàn
      const newStatus = {};
      STORES.forEach(store => {
        // Kiểm tra xem có sản phẩm nào từ sàn này không
        const hasProducts = resultProducts.some(p => SOURCE_TO_KEY[p.source] === store.key);
        newStatus[store.key] = hasProducts ? 'done' : 'empty';
      });
      setStoreStatus(newStatus);
    } catch (err) {
      console.error("Lỗi gọi API:", err);
      setError("Không thể kết nối đến máy chủ hoặc có lỗi xảy ra.");
      
      // Nếu lỗi, đánh dấu tất cả là lỗi
      const errorStatus = {};
      STORES.forEach(store => {
        errorStatus[store.key] = 'error';
      });
      setStoreStatus(errorStatus);
    } finally {
      setLoading(false);
    }
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
