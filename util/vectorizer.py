# -*- coding: utf-8 -*-
import arrow
import numpy as np
import gensim
from tqdm import tqdm
from typing import List
from numba import njit
from numba import types
from numba.typed import Dict
from numba.core.errors import NumbaDeprecationWarning, NumbaPendingDeprecationWarning
import warnings
warnings.simplefilter('ignore', category=NumbaDeprecationWarning)
warnings.simplefilter('ignore', category=NumbaPendingDeprecationWarning)

from pecanpy.cli import Timer


class BaseVectorizer():

    def __init__(
        self,
        vecs: gensim.models.keyedvectors.KeyedVectors,
    ):
        self.vecs = vecs
        self.embs = []

    def _map_word2vec(self):
        word2vec = Dict.empty(
            key_type=types.unicode_type,
            value_type=types.float32[:],
        )

        for word in self.vecs.key_to_index:
            vector = self.vecs[word]
            word2vec[word] = np.array(vector, dtype=np.float32)

        return word2vec

    @Timer('to save embeddings')
    def save_embs_format(self, output_dir: str, file_name: str):
        if len(self.embs) > 0:
            """
            out_file = '{}{}-{}-{}d-{}.{}'.format(
                output_dir if output_dir.endswith('/') else output_dir + '/',
                file_name,
                arrow.utcnow().format('YYYYMMDD-HHmm'),
                len(self.vecs.vectors[0]),  # dimensions
                self.__class__.__name__,
                'txt',
            )
            """
            out_file = '{}{}.{}'.format(
                output_dir if output_dir.endswith('/') else output_dir + '/',
                file_name,
                'txt',
            )
            with open(out_file, 'w'):
                np.savetxt(out_file, self.embs)
        else:
            raise ValueError('Fail to save embeddings')


class SeqVectorizer(BaseVectorizer):

    def __init__(self, vecs):
        BaseVectorizer.__init__(self, vecs)

    @Timer('to get sequence-level embeddings')
    def train(self, sentences: List[str], vector_size: int = 128, mode: str = 'mean_pool'):
        """ mode:'mean_pool', 'max_pool', 'mean_concat_max_pool, 'hier_pool'
            Note that mode of 'mean_concat_max_pool' is only recommended
            for short sequences (e.g., 150bp segments).
        """
        word2vec = BaseVectorizer._map_word2vec(self)
        dimensions = len(self.vecs.vectors[0])

        # averaging vectors
        @njit(fastmath=True, nogil=True)
        def mean_pool(sentence, word2vec_diz, vector_size=vector_size):
            embedding = np.zeros((vector_size,), dtype=np.float32)
            bow = sentence.split()
            for word in bow:
                embedding += word2vec_diz[word]
            return embedding / float(len(bow))

        # max pool vectors
        @njit(fastmath=True, nogil=True)
        def max_pool(sentence, word2vec_diz, vector_size=vector_size):
            embedding = np.zeros((vector_size,), dtype=np.float32)
            bow = sentence.split()
            for word in bow:
                word_vec = word2vec_diz[word]
                for bit in range(0, vector_size+1):
                    if word_vec[bit] > embedding[bit]:
                        embedding[bit] = word_vec[bit]
            return embedding

        # hierarchical pool vectors
        @njit(fastmath=True, nogil=True)
        def hier_pool(sentence, word2vec_diz, window_size=2, vector_size=vector_size):
            bow = sentence.split()
            embedding = np.zeros((vector_size,), dtype=np.float32)
            idx = 0
            while (idx < len(bow)):
                mean_embedding = np.zeros((vector_size,), dtype=np.float32)

                # local mean pool at a sliding window
                for word in bow[idx:idx+window_size]:
                    mean_embedding += word2vec_diz[word]
                mean_embedding /= window_size

                # global max pool across sliding windows
                for bit in range(0, vector_size+1):
                    if mean_embedding[bit] > embedding[bit]:
                        embedding[bit] = mean_embedding[bit]

                idx += window_size - 1

            return embedding

        for i in tqdm(range(len(sentences))):
            if mode == 'mean_pool':
                emb = mean_pool(sentences[i], word2vec, vector_size=dimensions)
            elif mode == 'max_pool':
                emb = max_pool(sentences[i], word2vec, vector_size=dimensions)
            elif mode == 'mean_concat_max_pool':
                emb1 = mean_pool(sentences[i], word2vec, vector_size=dimensions)
                emb2 = max_pool(sentences[i], word2vec, vector_size=dimensions)
                emb = np.concatenate((emb1, emb2))  # dimensions = 2*dimensions
            else:  # hier_pool
                emb = hier_pool(sentences[i], word2vec, window_size=2, vector_size=dimensions)
            self.embs.append(emb)

        self.embs = np.array(self.embs)

