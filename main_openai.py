import asyncio
import aiohttp
from openai import OpenAI
import time
import re
import multiprocessing
import logging
from googlesearch import search
import chardet
from flask import Flask, render_template, request
import shutil
import lxml.html
from dotenv import load_dotenv
import os

app = Flask(__name__)

load_dotenv()

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL')
openai_client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10

async def perform_google_search(search_query, output_file):
    try:
        result_links = []
        for link in search(search_query, num_results=10):
            result_links.append(link)

        with open(output_file, 'w') as file:
            for link in result_links:
                file.write(link + '\n')

        logger.info(f"Search results have been saved to {output_file}.")
    except Exception as e:
        logger.error(f"Error during Google search: {str(e)}")

async def scrape_plaintext(url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                content_bytes = await response.read()
                detected_encoding = chardet.detect(content_bytes)['encoding']
                html = content_bytes.decode(detected_encoding or 'utf-8', errors='replace')
                tree = lxml.html.fromstring(html)

                title = tree.findtext('.//title')
                main_content = tree.find('.//main')
                if main_content is not None:
                    main_text = main_content.text_content()
                else:
                    main_text = tree.find('.//body').text_content()

                plaintext = f"Title: {title}\n\nMain Content:\n{main_text}"
                return plaintext
        except (aiohttp.ClientError, aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError, UnicodeDecodeError) as e:
            logger.error(f"Error accessing URL: {url}\nError message: {str(e)}")
            return f"Error accessing URL: {url}\nError message: {str(e)}"

def clean_text(text):
    cleaned_text = re.sub(r'[^\w\s]', '', text)
    cleaned_text = ' '.join(cleaned_text.split())
    return cleaned_text

async def scrape_and_save(url, output_folder, url_index):
    try:
        youtube_regex = re.compile(r'^(https?://)?(www\.)?youtube\.com/')
        if youtube_regex.match(url):
            logger.info(f"Skipping YouTube URL: {url}")
            return

        output_file = os.path.join(output_folder, f'URL{url_index}output.txt')
        plaintext = await scrape_plaintext(url)
        cleaned_text = clean_text(plaintext)
        truncated_text = cleaned_text[:50000]  # Truncate to approximately 50KB
        with open(output_file, 'w', encoding='utf-8') as file:
            file.write(truncated_text)
        logger.info(f"Data for URL{url_index} has been saved to {output_file}.")
    except Exception as e:
        logger.error(f"Error scraping and saving URL {url_index}: {str(e)}")

def summarize_with_gpt(input_file, prompt, result_queue):
    try:
        with open(input_file, 'r', encoding='utf-8') as file:
            content = file.read()

        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt + content}
            ],
            max_tokens=4096,
            temperature=0.7,
            top_p=0.9
        )
        result_text = response.choices[0].message.content
        result_queue.put(result_text)
        logger.info(f"Summarization complete for {input_file}.")
    except Exception as e:
        logger.error(f"Error during summarization: {str(e)}")
        result_queue.put("")


def compile_summaries(summaries_folder, compiled_summary_file, urls):
    try:
        summaries = []
        for i, url in enumerate(urls, start=1):
            summary_file = os.path.join(summaries_folder, f'URL{i}Summary.txt')
            if os.path.exists(summary_file):
                with open(summary_file, 'r', encoding='utf-8') as file:
                    summary = file.read()
                    summaries.append(summary)

        compiled_summary = "\n".join(summaries)
        with open(compiled_summary_file, 'w', encoding='utf-8') as file:
            file.write(compiled_summary)
        logger.info(f"All summaries have been compiled into {compiled_summary_file}.")
    except Exception as e:
        logger.error(f"Error compiling summaries: {str(e)}")

async def main(search_query):
    start_time = time.time()
    logger.info("Starting the main function...")

    output_folder = 'URLoutput'
    shutil.rmtree(output_folder, ignore_errors=True)
    os.makedirs(output_folder, exist_ok=True)

    summaries_folder = 'URLsummaries'
    shutil.rmtree(summaries_folder, ignore_errors=True)
    os.makedirs(summaries_folder, exist_ok=True)

    logger.info("Performing Google search and saving result links to URLS.txt...")
    await perform_google_search(search_query, 'URLS.txt')

    logger.info("Scraping and saving website plaintext data...")
    with open('URLS.txt', 'r') as file:
        urls = file.read().splitlines()

    batch_size = 5
    for i in range(0, len(urls), batch_size):
        batch_urls = urls[i:i+batch_size]
        tasks = []
        for j, url in enumerate(batch_urls, start=i+1):
            task = asyncio.create_task(scrape_and_save(url, output_folder, j))
            tasks.append(task)
        await asyncio.gather(*tasks)

    logger.info(f"Website plaintext data has been saved to {output_folder}.")

    logger.info("Summarizing webpages using GPT-3.5 Turbo...")
    summary_processes = []
    result_queues = []
    for i in range(1, len(urls)+1, 2):
        for j in range(i, min(i + 2, len(urls)+1)):
            input_file = os.path.join(output_folder, f'URL{j}output.txt')
            if os.path.exists(input_file):
                result_queue = multiprocessing.Queue()
                process = multiprocessing.Process(target=summarize_with_gpt, args=(input_file, "Summarize the information from the webpage in this document:", result_queue))
                process.start()
                summary_processes.append(process)
                result_queues.append(result_queue)

        for process in summary_processes:
            process.join()

        for j, result_queue in enumerate(result_queues, start=i):
            summary = result_queue.get()
            summary_file = os.path.join(summaries_folder, f'URL{j}Summary.txt')
            with open(summary_file, 'w', encoding='utf-8') as file:
                file.write(summary)
            logger.info(f"Summary for URL{j} has been saved to {summary_file}.")

        summary_processes.clear()
        result_queues.clear()

    logger.info("Compiling individual summaries into a single file...")
    compiled_summary_file = os.path.join(summaries_folder, 'URLsummaries.txt')
    compile_summaries(summaries_folder, compiled_summary_file, urls)

    logger.info("Summarizing the compiled summary file using GPT-3.5 Turbo...")
    final_summary_prompt = """I would like to receive all of the information and content from the following compilation of summaries, also summarized in a condensed format. Do not leave any info out, but ignore errors and do not include them in the summary. List each topic in list format with details next to it."""

    final_summary_queue = multiprocessing.Queue()
    summarize_with_gpt(compiled_summary_file, final_summary_prompt, final_summary_queue)
    final_summary = final_summary_queue.get()
    final_summary_file = 'Finalsummary.txt'
    with open(final_summary_file, 'w', encoding='utf-8') as file:
        file.write(final_summary)
    logger.info(f"Final summary has been saved to {final_summary_file}.")

    end_time = time.time()
    logger.info(f"Main function completed in {end_time - start_time:.2f} seconds.")
    return final_summary

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        search_query = request.form['search_query']
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        final_summary = loop.run_until_complete(main(search_query))
        with open('Finalsummary.txt', 'r', encoding='utf-8') as file:
            final_summary_text = file.read()

        with open('Finalsummary.txt', 'w', encoding='utf-8'):
            pass

        return render_template('index.html', final_summary=final_summary_text)
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=5005)
