from playwright.sync_api import sync_playwright
import time
import os

def create_demo_screenshots():
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Navigate to the platform
            page.goto("http://127.0.0.1:8000/login")
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            page.screenshot(path="screenshots/01_login.png", full_page=True)

            # Navigate to main dashboard
            page.goto("http://127.0.0.1:8000/")
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            page.screenshot(path="screenshots/02_dashboard.png", full_page=True)

            # Navigate to employees page
            page.goto("http://127.0.0.1:8000/employees")
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            page.screenshot(path="screenshots/03_employees.png", full_page=True)

            # Navigate to tasks page
            page.goto("http://127.0.0.1:8000/tasks")
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            page.screenshot(path="screenshots/04_tasks.png", full_page=True)

            # Navigate to support tickets
            page.goto("http://127.0.0.1:8000/support")
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            page.screenshot(path="screenshots/05_support.png", full_page=True)

            print("Demo screenshots created successfully!")

        except Exception as e:
            print(f"Error during demo: {e}")

        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    # Create directories
    os.makedirs("screenshots", exist_ok=True)
    create_demo_screenshots()