from theano import tensor

from fuel.transformers import Batch
from fuel.streams import DataStream
from fuel.schemes import ConstantScheme, ShuffledExampleScheme
from blocks.bricks import application, MLP, Rectifier, Initializable

import data
from data import transformers
from data.hdf5 import TaxiDataset, TaxiStream
from data.cut import TaxiTimeCutScheme
from model import ContextEmbedder


class FFMLP(Initializable):
    def __init__(self, config, output_layer=None, **kwargs):
        super(FFMLP, self).__init__(**kwargs)
        self.config = config

        self.context_embedder = ContextEmbedder(config)

        output_activation = [] if output_layer is None else [output_layer()]
        output_dim = [] if output_layer is None else [config.dim_output]
        self.mlp = MLP(activations=[Rectifier() for _ in config.dim_hidden] + output_activation,
                       dims=[config.dim_input] + config.dim_hidden + output_dim)

        self.extremities = {'%s_k_%s' % (side, ['latitude', 'longitude'][axis]): axis for side in ['first', 'last'] for axis in [0, 1]}
        self.inputs = self.context_embedder.inputs + self.extremities.keys()
        self.children = [ self.context_embedder, self.mlp ]

    def _push_initialization_config(self):
        self.mlp.weights_init = self.config.mlp_weights_init
        self.mlp.biases_init = self.config.mlp_biases_init

    @application(outputs=['prediction'])
    def predict(self, **kwargs):
        embeddings = tuple(self.context_embedder.apply(**{k: kwargs[k] for k in self.context_embedder.inputs }))
        extremities = tuple((kwargs[k] - data.train_gps_mean[v]) / data.train_gps_std[v] for k, v in self.extremities.items())

        inputs = tensor.concatenate(extremities + embeddings, axis=1)
        outputs = self.mlp.apply(inputs)

        return outputs

    @predict.property('inputs')
    def predict_inputs(self):
        return self.inputs

class Stream(object):
    def __init__(self, config):
        self.config = config

    def train(self, req_vars):
        stream = TaxiDataset('train')
        stream = DataStream(stream, iteration_scheme=TaxiTimeCutScheme())

        valid = TaxiDataset(self.config.valid_set, 'valid.hdf5', sources=('trip_id',))
        valid_trips_ids = valid.get_data(None, slice(0, valid.num_examples))[0]

        stream = transformers.TaxiExcludeTrips(valid_trips_ids, stream)
        stream = transformers.TaxiGenerateSplits(stream, max_splits=1)

        stream = transformers.TaxiAddDateTime(stream)
        stream = transformers.TaxiAddFirstLastLen(self.config.n_begin_end_pts, stream)
        stream = transformers.Select(stream, tuple(req_vars))
        return Batch(stream, iteration_scheme=ConstantScheme(self.config.batch_size))

    def valid(self, req_vars):
        stream = TaxiStream(self.config.valid_set, 'valid.hdf5')

        stream = transformers.TaxiAddDateTime(stream)
        stream = transformers.TaxiAddFirstLastLen(self.config.n_begin_end_pts, stream)
        stream = transformers.Select(stream, tuple(req_vars))
        return Batch(stream, iteration_scheme=ConstantScheme(1000))

    def test(self, req_vars):
        stream = TaxiStream('test')
        
        stream = transformers.TaxiAddDateTime(stream)
        stream = transformers.TaxiAddFirstLastLen(self.config.n_begin_end_pts, stream)

        return Batch(stream, iteration_scheme=ConstantScheme(1))

    def inputs(self):
        return {'call_type': tensor.bvector('call_type'),
                'origin_call': tensor.ivector('origin_call'),
                'origin_stand': tensor.bvector('origin_stand'),
                'taxi_id': tensor.wvector('taxi_id'),
                'timestamp': tensor.ivector('timestamp'),
                'day_type': tensor.bvector('day_type'),
                'missing_data': tensor.bvector('missing_data'),
                'latitude': tensor.matrix('latitude'),
                'longitude': tensor.matrix('longitude'),
                'destination_latitude': tensor.vector('destination_latitude'),
                'destination_longitude': tensor.vector('destination_longitude'),
                'travel_time': tensor.ivector('travel_time'),
                'first_k_latitude': tensor.matrix('first_k_latitude'),
                'first_k_longitude': tensor.matrix('first_k_longitude'),
                'last_k_latitude': tensor.matrix('last_k_latitude'),
                'last_k_longitude': tensor.matrix('last_k_longitude'),
                'input_time': tensor.ivector('input_time'),
                'week_of_year': tensor.bvector('week_of_year'),
                'day_of_week': tensor.bvector('day_of_week'),
                'qhour_of_day': tensor.bvector('qhour_of_day')}