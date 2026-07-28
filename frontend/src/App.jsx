import React from 'react'
import SearchProduct from './components/SearchProduct'

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <h1>
            <span className="logo-icon">🔍</span>
            So Sánh Giá Sản Phẩm
          </h1>
          <p className="subtitle">
            Tra cứu giá từ 7 cửa hàng công nghệ hàng đầu Việt Nam
          </p>
        </div>
      </header>
      <main>
        <SearchProduct />
      </main>
      <footer className="app-footer">
        <p>Dữ liệu được thu thập từ các trang thương mại điện tử đối tác</p>
      </footer>
    </div>
  )
}

export default App

