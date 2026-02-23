import asyncio
import os
import sys
from pyppeteer import launch

# Path to local Chrome detected on Windows
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

async def main():
    os.makedirs('screenshots', exist_ok=True)
    print('Launching Chrome at', CHROME_PATH)
    browser = await launch(executablePath=CHROME_PATH, headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
    page = await browser.newPage()
    await page.setViewport({'width': 1400, 'height': 900})
    url = 'http://localhost:8501'
    print('Navigating to', url)
    try:
        await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 60000})
        await page.waitForSelector('h1', timeout=60000)
    except Exception as e:
        print('Warning: could not fully wait for page load or selector:', e)
    await asyncio.sleep(1)
    out_path = os.path.join('screenshots', 'app_screenshot.png')
    await page.screenshot({'path': out_path, 'fullPage': True})
    print('Screenshot saved to', out_path)
    await browser.close()

if __name__ == '__main__':
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except Exception as e:
        print('Error while taking screenshot:', e)
        sys.exit(2)
