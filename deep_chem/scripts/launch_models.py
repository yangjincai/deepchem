"""
Convenience script to train basic models on supported datasets.
"""
import numpy as np
from deep_chem.models.keras import fit_singletask_mlp
from deep_chem.models.keras import fit_multitask_mlp
from deep_chem.models.keras import train_multitask_model
from deep_chem.models.sklearn import fit_singletask_models
from deep_chem.models.sklearn import fit_multitask_rf
from deep_chem.utils.analysis import compare_datasets
from deep_chem.utils.evaluate import eval_model
from deep_chem.utils.evaluate import compute_roc_auc_scores
from deep_chem.utils.evaluate import compute_r2_scores
from deep_chem.utils.evaluate import compute_rms_scores
from deep_chem.utils.load import get_target_names
from deep_chem.utils.load import load_datasets
from deep_chem.utils.load import load_and_transform_dataset
from deep_chem.utils.preprocess import dataset_to_numpy
from deep_chem.utils.preprocess import train_test_random_split
from deep_chem.utils.preprocess import train_test_scaffold_split
from deep_chem.utils.preprocess import scaffold_separate
from deep_chem.utils.preprocess import multitask_to_singletask

def filter_outliers(X, y):
  """Removes outlier values from dataset.

  Parameters
  ----------
  X: np.ndarray
    Training features
  y: np.ndarray
    Training labels.
  """
  Xclean, yclean = [], []
  for index, elt in enumerate(y):
    if y[index] > 60:
      continue
    Xclean.append(X[index])
    yclean.append(y[index])
  Xclean, yclean = np.array(Xclean), np.array(yclean)
  print "np.shape(Xclean): " + str(np.shape(Xclean))
  print "np.shape(yclean): " + str(np.shape(yclean))
  return Xclean, yclean

def analyze_data(dataset, splittype="random"):
  """Analyzes regression dataset.

  Parameters
  ----------
  dataset: dict
    A dictionary of type produced by load_datasets.
  splittype: string
    Type of split for train/test. Either random or scaffold.
  """
  singletask = multitask_to_singletask(dataset)
  for target in singletask:
    data = singletask[target]
    if len(data.keys()) == 0:
      continue
    if splittype == "random":
      train, test = train_test_random_split(data, seed=0)
    elif splittype == "scaffold":
      train, test = train_test_scaffold_split(data)
    else:
      raise ValueError("Improper splittype. Must be random/scaffold.")
    Xtrain, ytrain = dataset_to_numpy(train)
    # TODO(rbharath): Take this out once debugging is completed
    ytrain = np.log(ytrain)
    mean = np.mean(ytrain)
    std = np.std(ytrain)
    minval = np.amin(ytrain)
    maxval = np.amax(ytrain)
    hist = np.histogram(ytrain)
    print target
    print "Mean: %f" % mean
    print "Std: %f" % std
    print "Min: %f" % minval
    print "Max: %f" % maxval
    print "Histogram: "
    print hist


if __name__ == "__main__":
  muv_path = "/home/rbharath/vs-datasets/muv"
  pcba_path = "/home/rbharath/vs-datasets/pcba"
  dude_path = "/home/rbharath/vs-datasets/dude"
  pfizer_path = "/home/rbharath/private-datasets/pfizer"
  regression_path = "/home/rbharath/molecule-net/phase1"


  task_types, task_transforms = get_default_task_types_and_transforms(
    {"muv": muv_path})
  desc_transforms = get_default_descriptor_transforms()


  #fit_singletask_models([muv_path], "RandomForestClassifier", task_types,
  #    task_transforms, splittype="scaffold")
  #fit_singletask_models([dude_path], "LogisticRegression", task_types,
  #    task_transforms, splittype="scaffold")
  
  #fit_multitask_mlp([muv_path, pfizer_path], task_types, task_transforms,
  #  desc_transforms, splittype="scaffold", add_descriptors=False,
  #  desc_weight=0.1, n_hidden=500, learning_rate = .01, dropout = .5,
  #  nb_epoch=50, decay=1e-4, validation_split=0.01)

  #fit_multitask_mlp([muv_path, pfizer_path], task_types, task_transforms,
  #  desc_transforms, splittype="scaffold", add_descriptors=False, n_hidden=500,
  #  nb_epoch=40, learning_rate=0.01, decay=1e-4, dropout = .5)
  fit_multitask_mlp([dude_path], task_types, task_transforms,
    desc_transforms, splittype="scaffold", add_descriptors=False, n_hidden=500,
    nb_epoch=40, learning_rate=0.01, decay=1e-4, dropout = .5)

  #fit_multitask_mlp([muv_path], task_types, task_transforms, desc_transforms,
  #  splittype="scaffold", add_descriptors=False, n_hidden=500,
  #  learning_rate=.01, dropout=.5, nb_epoch=30, decay=1e-4)
  #fit_singletask_mlp([muv_path], task_types, task_transforms, desc_transforms,
  #  splittype="scaffold", add_descriptors=False, n_hidden=500,
  #  learning_rate=.01, dropout=.5, nb_epoch=30, decay=1e-4)
