import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        page.on("console", lambda msg: print(f"Browser console [{msg.type}]: {msg.text}"))
        
        await page.goto("http://localhost:8000/", wait_until="networkidle")
        
        # Type into the textarea
        await page.fill("#query-input", "hello, who are you? say pong")
        
        # Click the send button
        await page.click("#send-btn")
        
        print("Waiting for response...")
        # Wait for the ai response bubble to finish (streaming finishes when the cursor is removed or button re-enabled)
        await page.wait_for_function("() => !document.getElementById('send-btn').disabled", timeout=30000)
        
        # Get the latest assistant bubble
        html = await page.evaluate("""() => {
            const bubbles = document.querySelectorAll('.msg.assistant .bubble');
            return bubbles[bubbles.length - 1] ? bubbles[bubbles.length - 1].innerHTML : 'not found';
        }""")
        print("Bubble HTML:\n", html)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
