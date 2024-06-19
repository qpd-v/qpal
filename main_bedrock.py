import asyncio
import aiohttp
import json
import re
import multiprocessing
from googlesearch import search
import boto3
import chardet
import shutil
import lxml.html
import logging
import time
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def perform_google_search(search_query, output_file):
    try:
        result_links = []
        for link in search(search_query, num_results=10):
            result_links.append(link)

        with open(output_file, 'w') as file:
            for link in result_links:
                file.write(link + '\n')

        logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Search results have been saved to {output_file}.")
    except Exception as e:
        logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error during Google search: {str(e)}")

async def scrape_plaintext(url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
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
        except (aiohttp.ClientError, UnicodeDecodeError) as e:
            logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error accessing URL: {url}\nError message: {str(e)}")
            return f"Error accessing URL: {url}\nError message: {str(e)}"

def remove_special_characters(text):
    return re.sub(r'[^\w\s]', '', text)

def remove_excessive_whitespace(text):
    return re.sub(r'\s+', ' ', text).strip()

async def scrape_and_save(url, output_folder, url_index):
    try:
        youtube_regex = re.compile(r'^(https?://)?(www\.)?youtube\.com/')
        if youtube_regex.match(url):
            logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Skipping YouTube URL: {url}")
            return

        output_file = os.path.join(output_folder, f'URL{url_index}output.txt')
        plaintext = await scrape_plaintext(url)
        cleaned_text = remove_special_characters(plaintext)
        text_without_excessive_whitespace = remove_excessive_whitespace(cleaned_text)
        truncated_text = text_without_excessive_whitespace[:100000]  # Truncate to approximately 100KB
        with open(output_file, 'w', encoding='utf-8') as file:
            file.write(truncated_text)
        logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Data for URL{url_index} has been saved to {output_file}.")
    except Exception as e:
        logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error scraping and saving URL {url_index}: {str(e)}")

def summarize_with_claude(input_file, prompt, result_queue):
    try:
        from dotenv import load_dotenv
        import os
        load_dotenv()

        AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
        AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
        AWS_REGION = os.environ.get('AWS_REGION')
        AWS_MODEL = os.environ.get('AWS_MODEL')

        bedrock_runtime = boto3.client(
            'bedrock-runtime',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        model_id = AWS_MODEL

        with open(input_file, 'r', encoding='utf-8') as file:
            content = file.read()

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": f"{prompt}\n\n{content}"
                }
            ]
        })

        response = bedrock_runtime.invoke_model(body=body, modelId=model_id)
        response_body = json.loads(response.get('body').read())

        summary = response_body['content'][0]['text'].strip()
        result_queue.put(summary)
        logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Summarization complete for {input_file}.")
    except Exception as e:
        logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error during summarization: {str(e)}")
        result_queue.put("")


def compile_summaries(summaries_folder, compiled_summary_file):
    try:
        summaries = []
        for i in range(1, 21):
            summary_file = os.path.join(summaries_folder, f'URL{i}Summary.txt')
            if os.path.exists(summary_file):
                with open(summary_file, 'r', encoding='utf-8') as file:
                    summary = file.read()
                    summaries.append(summary)

        compiled_summary = "\n".join(summaries)
        with open(compiled_summary_file, 'w', encoding='utf-8') as file:
            file.write(compiled_summary)
        logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] All summaries have been compiled into {compiled_summary_file}.")
    except Exception as e:
        logger.error(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error compiling summaries: {str(e)}")

def summarize_and_save(input_file, summary_file, result_queue):
    if os.path.exists(input_file):
        summarize_with_claude(input_file, "Summarize the information. Be thorough:", result_queue)
        summary = result_queue.get()
        with open(summary_file, 'w', encoding='utf-8') as file:
            file.write(summary)
        logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Summary for {input_file} has been saved to {summary_file}.")

async def main(search_query):
    start_time = time.time()
    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting the main function...")

    # Clear existing data
    output_folder = 'URLoutput'
    shutil.rmtree(output_folder, ignore_errors=True)
    os.makedirs(output_folder, exist_ok=True)

    summaries_folder = 'URLsummaries'
    shutil.rmtree(summaries_folder, ignore_errors=True)
    os.makedirs(summaries_folder, exist_ok=True)

    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Performing Google search and saving result links to URLS.txt...")
    await perform_google_search(search_query, 'URLS.txt')

    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Scraping and saving website plaintext data...")
    with open('URLS.txt', 'r') as file:
        urls = file.read().splitlines()

    tasks = []
    for i, url in enumerate(urls, start=1):
        task = asyncio.create_task(scrape_and_save(url, output_folder, i))
        tasks.append(task)

    await asyncio.gather(*tasks)

    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Website plaintext data has been saved to {output_folder}.")

    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Summarizing webpages using Claude 3 Haiku...")
    with multiprocessing.Pool() as pool:
        result_queue = multiprocessing.Manager().Queue()
        summarization_tasks = []
        for i in range(1, 21):
            input_file = os.path.join(output_folder, f'URL{i}output.txt')
            summary_file = os.path.join(summaries_folder, f'URL{i}Summary.txt')
            summarization_task = pool.apply_async(summarize_and_save, args=(input_file, summary_file, result_queue))
            summarization_tasks.append(summarization_task)

        for task in summarization_tasks:
            task.wait()

    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Compiling individual summaries into a single file...")
    compiled_summary_file = os.path.join(summaries_folder, 'URLsummaries.txt')
    compile_summaries(summaries_folder, compiled_summary_file)

    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Summarizing the compiled summary file using Claude 3 Haiku...")
    final_summary_prompt = """Here is a compilation of summaries that were generated from various webpages. Provide ALL of the details from the information. There will be varyibg topics. Be very thorough but make sure to remove all duplicate information.
                          """

    final_summary_queue = multiprocessing.Queue()
    summarize_with_claude(compiled_summary_file, final_summary_prompt, final_summary_queue)
    final_summary = final_summary_queue.get()
    final_summary_file = 'Finalsummary.txt'
    with open(final_summary_file, 'w', encoding='utf-8') as file:
        file.write(final_summary)
    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Final summary has been saved to {final_summary_file}.")

    end_time = time.time()
    logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Main function completed in {end_time - start_time:.2f} seconds.")
    return final_summary
