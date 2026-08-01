from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


# Hàm cào chi tiết bình luận sản phẩm
def crawl_product_detail(product):
  link = product["link"]
  if not link:
    product["comments"] = []
    return product

  with sync_playwright() as p:
    try:
      browser = p.chromium.launch(headless=True)
      page = browser.new_page()
      page.goto(link, timeout=60000)
      page.wait_for_load_state("networkidle")

      # Click nút "Xem thêm đánh giá" liên tục cho đến khi ẩn/hết
      load_more_comment_selector = ".btn-load-review"
      while True:
        try:
          btn = page.locator(load_more_comment_selector)
          if btn.is_visible():
            btn.click()
            time.sleep(1.5)  # Chờ load thêm nội dung
          else:
            break
        except Exception:
          break

      html_content = page.content()
      browser.close()

      # Phân tích cú pháp HTML của trang chi tiết
      soup = BeautifulSoup(html_content, "html.parser")

      # Chỉ lấy nội dung cmt từ các thẻ .item-content thuộc phần bình luận
      comment_elements = soup.select(
          ".comments-content .comments-list .item-content"
      )
      comments = [
          c.get_text(strip=True) for c in comment_elements if c.get_text(strip=True)
      ]
      product["comments"] = comments

    except Exception:
      product["comments"] = []

  return product


# Hàm lấy danh sách sản phẩm từ trang danh mục
def get_product_list(category_url):
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print(f"Đang truy cập danh mục: {category_url}")
    page.goto(category_url)
    page.wait_for_load_state("networkidle")

    # Click nút "Xem thêm sản phẩm" liên tục cho đến hết
    print("Đang tiến hành click nút 'Xem thêm sản phẩm'...")
    load_more_selector = "a.btn-show-more"

    while True:
      try:
        button = page.locator(load_more_selector)
        if button.is_visible():
          button.click()
          time.sleep(2)
        else:
          break
      except Exception:
        break

    print("Đã tải xong toàn bộ danh sách sản phẩm trên trang.")
    html_content = page.content()
    browser.close()

    soup = BeautifulSoup(html_content, "html.parser")
    product_cards = soup.select(".list-products__item")

    print(f"Tìm thấy tổng cộng {len(product_cards)} sản phẩm.")

    products_list = []
    for card in product_cards:
      a_tag = card.select_one("a")
      link = ""
      if a_tag and a_tag.has_attr("href"):
        link = a_tag["href"]
        if link.startswith("/"):
          link = "https://clickbuy.com.vn" + link

      name_elem = card.select_one(".title_name")
      name = name_elem.get_text(strip=True) if name_elem else "Không có tên"

      price_elem = card.select_one(".new-price")
      price = price_elem.get_text(strip=True) if price_elem else "Liên hệ"

      img_elem = card.select_one(".thumbnail img")
      image_url = ""
      if img_elem:
        image_url = (
            img_elem.get("data-src")
            or img_elem.get("src")
            or img_elem.get("data-original")
            or ""
        )

      products_list.append({
          "name": name,
          "price": price,
          "image": image_url,
          "link": link,
      })

    return products_list


if __name__ == "__main__":
  target_url = "https://clickbuy.com.vn/dien-thoai"

  start_time = time.time()
  products = get_product_list(target_url)

  if products:
    print(
        "\nBắt đầu cào chi tiết và bình luận bằng ĐA LUỒNG (ThreadPoolExecutor)..."
    )

    max_threads = 5  # Giảm số luồng xuống 1 chút vì dùng Playwright giả lập trình duyệt cào chi tiết
    results = []

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
      future_to_product = {
          executor.submit(crawl_product_detail, prod): prod for prod in products
      }

      for i, future in enumerate(as_completed(future_to_product), 1):
        res = future.result()
        results.append(res)
        print(
            f"[{i}/{len(products)}] Xong: {res['name']} | Số bình luận:"
            f" {len(res['comments'])}"
        )

    print(
        f"\n🎉 Hoàn tất! Tổng thời gian thực thi: {time.time() - start_time:.2f}"
        " giây."
    )

    if results:
      print("\n--- MẪU KẾT QUẢ SẢN PHẨM ĐẦU TIÊN ---")
      print(f"Tên: {results[0]['name']}")
      print(f"Giá: {results[0]['price']}")
      print(f"Link: {results[0]['link']}")
      print(f"Danh sách bình luận: {results[0]['comments']}")