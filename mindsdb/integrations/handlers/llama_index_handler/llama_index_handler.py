import os
from typing import Optional, Dict

import openai
import pandas as pd
from langchain.llms import OpenAI
import llama_index
from llama_index.readers.schema.base import Document
from llama_index import SimpleWebPageReader, QuestionAnswerPrompt
from llama_index import ServiceContext, StorageContext, load_index_from_storage
from llama_index import LLMPredictor, OpenAIEmbedding
from llama_index.indices.vector_store.base import VectorStore

from mindsdb.integrations.libs.base import BaseMLEngine
from mindsdb.utilities.config import Config


class LlamaIndexHandler(BaseMLEngine):
    """ Integration with the LlamaIndex data framework for LLM applications. """
    name = 'llama_index'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generative = True
        self.default_index_class = 'GPTVectorStoreIndex'
        self.supported_index_class = ['GPTVectorStoreIndex']
        self.default_reader = 'DFReader'
        self.supported_reader = ['DFReader', 'SimpleWebPageReader']

    def create(self, target: str, df: Optional[pd.DataFrame] = None, args: Optional[Dict] = None) -> None:
        if 'using' not in args:
            raise Exception("LlamaIndex engine requires a USING clause! Refer to its documentation for more details.")

        if 'prompt_template' in args['using']:
            self._validate_prompt_template(args['using']['prompt_template'])

        if 'index_class' not in args['using']:
            args['using']['index_class'] = self.default_index_class
        elif args['using']['index_class'] not in self.supported_index_class:
            raise Exception(f"Invalid index class argument. Please use one of {self.supported_index_class}")

        if 'reader' not in args['using']:
            args['using']['reader'] = self.default_reader
        elif args['using']['reader'] not in self.supported_reader:
            raise Exception(f"Invalid operation mode. Please use one of {self.supported_reader}")

        if args['using']['reader'] == 'DFReader':
            dstrs = df.apply(lambda x: ', '.join([f'{col}: {str(entry)}' for col, entry in zip(df.columns, x)]), axis=1)
            reader = list(map(lambda x: Document(x), dstrs.tolist()))

        elif args['using']['reader'] == 'SimpleWebPageReader':
            if 'source_url_link' not in args['using']:
                raise Exception("SimpleWebPageReader requires a `source_url_link` parameter. Refer to LlamaIndex documentation for more details.")  # noqa

            reader = SimpleWebPageReader(html_to_text=True).load_data([args['using']['source_url_link']])

        else:
            raise Exception(f"Invalid operation mode. Please use one of {self.supported_reader}.")

        self.model_storage.json_set('args', args)
        index = self._setup_index(reader)
        path = self.model_storage.fileStorage.get_path('./')
        index.storage_context.persist(persist_dir=path)

    def predict(self, df: Optional[pd.DataFrame] = None, args: Optional[Dict] = None) -> pd.DataFrame:
        args = self.model_storage.json_get('args')
        input_column = args['using'].get('input_column', None)
        engine_kwargs = {}

        prompt_template = args['using'].get('prompt_template', args.get('prompt_template', None))
        if prompt_template is not None:
            self._validate_prompt_template(prompt_template)
            engine_kwargs['text_qa_template'] = QuestionAnswerPrompt(prompt_template)

        if input_column is None:
            raise Exception(
                '`input_column` must be provided at model creation time or through USING clause when predicting. Please try again.'
            )

        if input_column not in df.columns:
            raise Exception(f'Column "{input_column}" not found in input data! Please try again.')

        index_path = self.model_storage.fileStorage.get_path('./')
        storage_context = StorageContext.from_defaults(persist_dir=index_path)
        service_context = self._get_service_context()
        index = load_index_from_storage(storage_context, service_context=service_context)
        query_engine = index.as_query_engine(**engine_kwargs)

        questions = df[input_column]
        results = []

        for question in questions:
            query_results = query_engine.query(question)  # TODO: provide extra_info in explain_target col
            results.append(query_results.response)

        return pd.DataFrame({'question': questions, args['target']: results})

    def _get_service_context(self):
        args = self.model_storage.json_get('args')
        openai_api_key = self._get_llama_index_api_key(args['using'])
        openai.api_key = openai_api_key  # TODO: shouldn't have to do this! bug?
        llm = OpenAI(openai_api_key=openai_api_key)  # TODO: all usual params should go here
        embed_model = OpenAIEmbedding(openai_api_key=openai_api_key)
        return ServiceContext.from_defaults(
            llm_predictor=LLMPredictor(llm=llm), embed_model=embed_model
        )
    
    def _setup_index(self, documents):
        args = self.model_storage.json_get('args')
        indexer: VectorStore = getattr(llama_index, args['using']['index_class'])
        return indexer.from_documents(
            documents, service_context=self._get_service_context()
        )

    def _validate_prompt_template(self, prompt_template: str):
        if '{context_str}' not in prompt_template or '{query_str}' not in prompt_template:
            raise Exception("Provided prompt template is invalid, missing one of `{context_str}` or `{query_str}`. Please ensure both placeholders are present and try again.")  # noqa

    def _get_llama_index_api_key(self, args, strict=True):
        """
        API_KEY preference order:
            1. provided at model creation
            2. provided at engine creation
            3. OPENAI_API_KEY env variable
            4. llama_index.OPENAI_API_KEY setting in config.json

        Note: method is not case sensitive.
        """
        key = 'OPENAI_API_KEY'
        for k in key, key.lower():
            # 1
            if args.get(k):
                return args[k]
            # 2
            connection_args = self.engine_storage.get_connection_args()
            if k in connection_args:
                return connection_args[k]
            # 3
            api_key = os.getenv(k)
            if api_key is not None:
                return api_key
            # 4
            config = Config()
            openai_cfg = config.get('llama_index', {})
            if k in openai_cfg:
                return openai_cfg[k]

        if strict:
            raise Exception(f'Missing API key "{k}". Either re-create this ML_ENGINE specifying the `{k}` parameter, or re-create this model and pass the API key with `USING` syntax.')  # noqa
