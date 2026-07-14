import streamlit as st
import pandas as pd
from datetime import datetime

class TokenCounter:
    PRICE_INPUT_PER_M = 0.075
    PRICE_OUTPUT_PER_M = 0.30

    def __init__(self):
        self._init_session()

    def _init_session(self):
        if 'token_stats' not in st.session_state:
            st.session_state.token_stats = {
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'total_requests': 0,
                'total_pages': 0,
                'sessions': [],
                'last_reset': datetime.now().strftime("%d/%m/%Y %H:%M"),
            }

    # AJOUT DE **kwargs POUR ACCEPTER 'file_name' SANS PLANTER
    def record_extraction(self, input_tokens, output_tokens, pages=0, **kwargs):
        """Enregistre l'usage. **kwargs permet d'ignorer les arguments en trop comme file_name."""
        
        file_name = kwargs.get('file_name', 'Document sans nom')
        
        cost = (
            (input_tokens / 1_000_000) * self.PRICE_INPUT_PER_M +
            (output_tokens / 1_000_000) * self.PRICE_OUTPUT_PER_M
        )
        
        st.session_state.token_stats['total_input_tokens'] += input_tokens
        st.session_state.token_stats['total_output_tokens'] += output_tokens
        st.session_state.token_stats['total_requests'] += 1
        st.session_state.token_stats['total_pages'] += pages
        
        new_session = {
            'Heure': datetime.now().strftime("%H:%M:%S"),
            'Fichier': file_name,
            'Pages': pages,
            'Tokens In': input_tokens,
            'Tokens Out': output_tokens,
            'Coût USD': cost
        }
        st.session_state.token_stats['sessions'].insert(0, new_session)

    def reset(self):
        st.session_state.token_stats = {
            'total_input_tokens': 0, 'total_output_tokens': 0,
            'total_requests': 0, 'total_pages': 0,
            'sessions': [], 'last_reset': datetime.now().strftime("%d/%m/%Y %H:%M")
        }
