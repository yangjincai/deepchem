from __future__ import division
from __future__ import unicode_literals

__author__ = "Joseph Gomes"
__copyright__ = "Copyright 2017, Stanford University"
__license__ = "MIT"

import sys

from deepchem.models.tensorgraph.layers import Layer, Feature, Label, AtomicConvolution, L2Loss, ReduceMean
from deepchem.models import TensorGraph

import numpy as np
import tensorflow as tf
import itertools


def InitializeWeightsBiases(prev_layer_size,
                            size,
                            weights=None,
                            biases=None,
                            name=None):
  """Initializes weights and biases to be used in a fully-connected layer.

  Parameters
  ----------
  prev_layer_size: int
    Number of features in previous layer.
  size: int
    Number of nodes in this layer.
  weights: tf.Tensor, optional (Default None)
    Weight tensor.
  biases: tf.Tensor, optional (Default None)
    Bias tensor.
  name: str
    Name for this op, optional (Defaults to 'fully_connected' if None)

  Returns
  -------
  weights: tf.Variable
    Initialized weights.
  biases: tf.Variable
    Initialized biases.

  """

  if weights is None:
    weights = tf.truncated_normal([prev_layer_size, size], stddev=0.01)
  if biases is None:
    biases = tf.zeros([size])

  with tf.name_scope(name, 'fully_connected', [weights, biases]):
    w = tf.Variable(weights, name='w')
    b = tf.Variable(biases, name='b')
  return w, b


class AtomicConvScore(Layer):

  def __init__(self, atom_types, layer_sizes, component, **kwargs):
    self.atom_types = atom_types
    self.layer_sizes = layer_sizes
    self.component = component
    super(AtomicConvScore, self).__init__(**kwargs)

  def create_tensor(self, in_layers=None, set_tensors=True, **kwargs):
    frag1_layer = self.in_layers[0].out_tensor
    frag2_layer = self.in_layers[1].out_tensor
    complex_layer = self.in_layers[2].out_tensor

    frag1_z = self.in_layers[3].out_tensor
    frag2_z = self.in_layers[4].out_tensor
    complex_z = self.in_layers[5].out_tensor

    atom_types = self.atom_types
    layer_sizes = self.layer_sizes
    num_layers = len(layer_sizes)
    weight_init_stddevs = [1 / np.sqrt(x) for x in layer_sizes]
    bias_init_consts = [0.0] * num_layers

    weights = []
    biases = []
    output_weights = []
    output_biases = []

    n_features = int(frag1_layer.get_shape()[-1])

    for ind, atomtype in enumerate(atom_types):

      prev_layer_size = n_features
      weights.append([])
      biases.append([])
      output_weights.append([])
      output_biases.append([])
      for i in range(num_layers):
        weight, bias = InitializeWeightsBiases(
            prev_layer_size=prev_layer_size,
            size=layer_sizes[i],
            weights=tf.truncated_normal(
                shape=[prev_layer_size, layer_sizes[i]],
                stddev=weight_init_stddevs[i]),
            biases=tf.constant(
                value=bias_init_consts[i], shape=[layer_sizes[i]]))
        weights[ind].append(weight)
        biases[ind].append(bias)
        prev_layer_size = layer_sizes[i]
      weight, bias = InitializeWeightsBiases(prev_layer_size, 1)
      output_weights[ind].append(weight)
      output_biases[ind].append(bias)

    def atomnet(current_input, atomtype):
      prev_layer = current_input
      for i in range(num_layers):
        layer = tf.nn.xw_plus_b(prev_layer, weights[atomtype][i],
                                biases[atomtype][i])
        layer = tf.nn.relu(layer)
        prev_layer = layer

      output_layer = tf.squeeze(
          tf.nn.xw_plus_b(prev_layer, output_weights[atomtype][0],
                          output_biases[atomtype][0]))
      return output_layer

    frag1_zeros = tf.zeros_like(frag1_z, dtype=tf.float32)
    frag2_zeros = tf.zeros_like(frag2_z, dtype=tf.float32)
    complex_zeros = tf.zeros_like(complex_z, dtype=tf.float32)

    frag1_atomtype_energy = []
    frag2_atomtype_energy = []
    complex_atomtype_energy = []

    for ind, atomtype in enumerate(atom_types):
      frag1_outputs = tf.map_fn(lambda x: atomnet(x, ind), frag1_layer)
      frag2_outputs = tf.map_fn(lambda x: atomnet(x, ind), frag2_layer)
      complex_outputs = tf.map_fn(lambda x: atomnet(x, ind), complex_layer)

      cond = tf.equal(frag1_z, atomtype)
      frag1_atomtype_energy.append(tf.where(cond, frag1_outputs, frag1_zeros))
      cond = tf.equal(frag2_z, atomtype)
      frag2_atomtype_energy.append(tf.where(cond, frag2_outputs, frag2_zeros))
      cond = tf.equal(complex_z, atomtype)
      complex_atomtype_energy.append(
          tf.where(cond, complex_outputs, complex_zeros))

    frag1_outputs = tf.add_n(frag1_atomtype_energy)
    frag2_outputs = tf.add_n(frag2_atomtype_energy)
    complex_outputs = tf.add_n(complex_atomtype_energy)

    frag1_energy = tf.reduce_sum(frag1_outputs, 1)
    frag2_energy = tf.reduce_sum(frag2_outputs, 1)
    complex_energy = tf.reduce_sum(complex_outputs, 1)
    if self.component == 'binding':
      target_energy = complex_energy - (frag1_energy + frag2_energy)
    elif self.component == 'complex':
      target_energy = complex_energy
    elif self.component == 'ligand':
      target_energy = complex_energy - frag1_energy
    elif self.component == 'protein':
      target_energy = complex_energy - frag2_energy
    else:
      raise ValueError('Unkown component {}'.format(self.component))
    self.out_tensor = tf.expand_dims(target_energy, axis=1)
    return self.out_tensor


class AtomicConvModel(TensorGraph):

  def __init__(
      self,
      frag1_num_atoms=70,
      frag2_num_atoms=634,
      complex_num_atoms=701,
      max_num_neighbors=12,
      batch_size=24,
      atom_types=[6, 7, 8, 9, 11, 12, 15, 16, 17, 20, 25, 30, 35, 53, -1],
      radial=[[
          1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0,
          8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0
      ], [0.0, 4.0, 8.0], [0.4]],
      layer_sizes=[32, 32, 16],
      learning_rate=0.001,
      component='binding',
      **kwargs):
    """Implements an Atomic Convolution Model.

    Implements the atomic convolutional networks as introduced in
    https://arxiv.org/abs/1703.10603. The atomic convolutional networks
    function as a variant of graph convolutions. The difference is that the
    "graph" here is the nearest neighbors graph in 3D space. The
    AtomicConvModel leverages these connections in 3D space to train models
    that learn to predict energetic state starting from the spatial
    geometry of the model.

    Params
    ------
    frag1_num_atoms: int
      Number of atoms in first fragment
    frag2_num_atoms: int
      Number of atoms in sec
    max_num_neighbors: int
      Maximum number of neighbors possible for an atom. Recall neighbors
      are spatial neighbors.  
    atom_types: list
      List of atoms recognized by model. Atoms are indicated by their
      nuclear numbers.
    radial: list
      TODO: add description
    layer_sizes: list
      TODO: add description
    learning_rate: float
      Learning rate for the model.
    """
    # TODO: Turning off queue for now. Safe to re-activate?
    super(AtomicConvModel, self).__init__(use_queue=False, **kwargs)
    self.complex_num_atoms = complex_num_atoms
    self.frag1_num_atoms = frag1_num_atoms
    self.frag2_num_atoms = frag2_num_atoms
    self.max_num_neighbors = max_num_neighbors
    self.batch_size = batch_size
    self.atom_types = atom_types
    self.component = component

    rp = [x for x in itertools.product(*radial)]
    self.frag1_X = Feature(shape=(batch_size, frag1_num_atoms, 3))
    self.frag1_nbrs = Feature(
        shape=(batch_size, frag1_num_atoms, max_num_neighbors))
    self.frag1_nbrs_z = Feature(
        shape=(batch_size, frag1_num_atoms, max_num_neighbors))
    self.frag1_z = Feature(shape=(batch_size, frag1_num_atoms))

    self.frag2_X = Feature(shape=(batch_size, frag2_num_atoms, 3))
    self.frag2_nbrs = Feature(
        shape=(batch_size, frag2_num_atoms, max_num_neighbors))
    self.frag2_nbrs_z = Feature(
        shape=(batch_size, frag2_num_atoms, max_num_neighbors))
    self.frag2_z = Feature(shape=(batch_size, frag2_num_atoms))

    if self.component == 'protein':
      complex_num_atoms = frag2_num_atoms
    if self.component == 'ligand':
      complex_num_atoms = frag1_num_atoms
    self.complex_X = Feature(shape=(batch_size, complex_num_atoms, 3))
    self.complex_nbrs = Feature(
        shape=(batch_size, complex_num_atoms, max_num_neighbors))
    self.complex_nbrs_z = Feature(
        shape=(batch_size, complex_num_atoms, max_num_neighbors))
    self.complex_z = Feature(shape=(batch_size, complex_num_atoms))

    frag1_conv = AtomicConvolution(
        atom_types=self.atom_types,
        radial_params=rp,
        boxsize=None,
        in_layers=[self.frag1_X, self.frag1_nbrs, self.frag1_nbrs_z])

    frag2_conv = AtomicConvolution(
        atom_types=self.atom_types,
        radial_params=rp,
        boxsize=None,
        in_layers=[self.frag2_X, self.frag2_nbrs, self.frag2_nbrs_z])

    complex_conv = AtomicConvolution(
        atom_types=self.atom_types,
        radial_params=rp,
        boxsize=None,
        in_layers=[self.complex_X, self.complex_nbrs, self.complex_nbrs_z])

    score = AtomicConvScore(
        self.atom_types,
        layer_sizes,
        component,
        in_layers=[
            frag1_conv, frag2_conv, complex_conv, self.frag1_z, self.frag2_z,
            self.complex_z
        ],
    )

    self.label = Label(shape=(None, 1))
    loss = ReduceMean(in_layers=L2Loss(in_layers=[score, self.label]))
    self.add_output(score)
    self.set_loss(loss)

  def default_generator(self,
                        dataset,
                        epochs=1,
                        predict=False,
                        deterministic=True,
                        pad_batches=True):
    complex_num_atoms = self.complex_num_atoms
    frag1_num_atoms = self.frag1_num_atoms
    frag2_num_atoms = self.frag2_num_atoms
    max_num_neighbors = self.max_num_neighbors
    batch_size = self.batch_size

    def replace_atom_types(z):

      def place_holder(i):
        if i in self.atom_types:
          return i
        return -1

      return np.array([place_holder(x) for x in z])

    for epoch in range(epochs):
      for ind, (F_b, y_b, w_b, ids_b) in enumerate(
          dataset.iterbatches(
              batch_size, deterministic=True, pad_batches=pad_batches)):
        N = complex_num_atoms
        N_1 = frag1_num_atoms
        N_2 = frag2_num_atoms
        M = max_num_neighbors

        # from batch_size x 3 x 4 to 3 x 4 x batch_size
        frag1, frag2, complex_ = np.transpose(F_b, axes=[1, 2, 0])
        frag1_Mol, frag1_X, frag1_Nbrs_dict, frag1_Z = frag1
        frag2_Mol, frag2_X, frag2_Nbrs_dict, frag2_Z = frag2
        complex_Mol, complex_X, complex_Nbrs_dict, complex_Z = complex_

        # vstack convert list of array objects into 2D array
        frag1_Z = np.vstack(frag1_Z)
        frag2_Z = np.vstack(frag2_Z)
        complex_Z = np.vstack(complex_Z)
        frag1_Z[np.isin(frag1_Z, self.atom_types, invert=True)] = -1
        frag2_Z[np.isin(frag2_Z, self.atom_types, invert=True)] = -1
        complex_Z[np.isin(complex_Z, self.atom_types, invert=True)] = -1

        frag1_Nbrs = np.zeros((batch_size, N_1, M))
        frag1_Nbrs_Z = np.zeros((batch_size, N_1, M))
        for i in range(batch_size):
          for idx, nbr_idxs in frag1_Nbrs_dict[i].items():
            n = len(nbr_idxs)
            frag1_Nbrs[i, idx, :n] = nbr_idxs
            frag1_Nbrs_Z[i, idx, :n] = frag1_Z[i, nbr_idxs]

        frag2_Nbrs = np.zeros((batch_size, N_2, M))
        frag2_Nbrs_Z = np.zeros((batch_size, N_2, M))
        for i in range(batch_size):
          for idx, nbr_idxs in frag2_Nbrs_dict[i].items():
            n = len(nbr_idxs)
            frag2_Nbrs[i, idx, :n] = nbr_idxs
            frag2_Nbrs_Z[i, idx, :n] = frag2_Z[i, nbr_idxs]

        complex_Nbrs = np.zeros((batch_size, N, M))
        complex_Nbrs_Z = np.zeros((batch_size, N, M))
        for i in range(batch_size):
          for idx, nbr_idxs in complex_Nbrs_dict[i].items():
            n = len(nbr_idxs)
            complex_Nbrs[i, idx, :n] = nbr_idxs
            complex_Nbrs_Z[i, idx, :n] = complex_Z[i, nbr_idxs]

        # vstack convert list of array objects into 2D (batch_size*N, 3) array
        # need reshape
        frag1_X = np.vstack(frag1_X).reshape(batch_size, N_1, 3)
        frag2_X = np.vstack(frag2_X).reshape(batch_size, N_2, 3)
        complex_X = np.vstack(complex_X).reshape(batch_size, N, 3)

        orig_dict = {}
        orig_dict[self.frag1_X] = frag1_X
        orig_dict[self.frag1_nbrs] = frag1_Nbrs
        orig_dict[self.frag1_nbrs_z] = frag1_Nbrs_Z
        orig_dict[self.frag1_z] = frag1_Z

        orig_dict[self.frag2_X] = frag2_X
        orig_dict[self.frag2_nbrs] = frag2_Nbrs
        orig_dict[self.frag2_nbrs_z] = frag2_Nbrs_Z
        orig_dict[self.frag2_z] = frag2_Z

        if self.component == 'protein':
          orig_dict[self.complex_X] = frag2_X
          orig_dict[self.complex_nbrs] = frag2_Nbrs
          orig_dict[self.complex_nbrs_z] = frag2_Nbrs_Z
          orig_dict[self.complex_z] = frag2_Z
        elif self.component == 'ligand':
          orig_dict[self.complex_X] = frag1_X
          orig_dict[self.complex_nbrs] = frag1_Nbrs
          orig_dict[self.complex_nbrs_z] = frag1_Nbrs_Z
          orig_dict[self.complex_z] = frag1_Z
        else:
          orig_dict[self.complex_X] =complex_X
          orig_dict[self.complex_nbrs] = complex_Nbrs
          orig_dict[self.complex_nbrs_z] = complex_Nbrs_Z
          orig_dict[self.complex_z] = complex_Z
        orig_dict[self.label] = np.reshape(y_b, newshape=(batch_size, 1))
        yield orig_dict

  def predict(self, dataset, transformers=[], outputs=None):
    """
    Uses self to make predictions on provided Dataset object.

    Parameters
    ----------
    dataset: dc.data.Dataset
      Dataset to make prediction on
    transformers: list
      List of dc.trans.Transformers.
    outputs: object
      If outputs is None, then will assume outputs=self.default_outputs. If outputs is
      a Layer/Tensor, then will evaluate and return as a single ndarray. If
      outputs is a list of Layers/Tensors, will return a list of ndarrays.

    Returns
    -------
    results: numpy ndarray or list of numpy ndarrays
    """
    generator = self.default_generator(dataset, predict=True, pad_batches=True)
    y_pred = self.predict_on_generator(generator, transformers, outputs)
    return y_pred[:len(dataset)]
