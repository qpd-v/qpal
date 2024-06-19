from flask import Flask, render_template, request
import asyncio

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    selected_model = 'bedrock'
    search_query = ''

    if request.method == 'POST':
        search_query = request.form['search_query']
        selected_model = request.form['model']

        if selected_model == 'bedrock':
            import main_bedrock
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            final_summary = loop.run_until_complete(main_bedrock.main(search_query))
        elif selected_model == 'anthropic':
            import main_anthropic
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            final_summary = loop.run_until_complete(main_anthropic.main(search_query))
        elif selected_model == 'openai':
            import main_openai
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            final_summary = loop.run_until_complete(main_openai.main(search_query))

        with open('Finalsummary.txt', 'r', encoding='utf-8') as file:
            final_summary_text = file.read()

        with open('Finalsummary.txt', 'w', encoding='utf-8'):
            pass

        return render_template('index.html', final_summary=final_summary_text, selected_model=selected_model, search_query=search_query)

    return render_template('index.html', selected_model=selected_model, search_query=search_query)

if __name__ == '__main__':
    app.run(debug=True, port=5005)
