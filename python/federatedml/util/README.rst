DataTransform(DataIO)
======

Data IO is the most basic component of Fate Algorithm module. 
It transforms the input Table to a Table whose values are Instance Object defined `here <../feature/instance.py>`_,
and what's more, the transformed table is the input data format of all other algorithm module, such as intersect、
homo LR and hetero LR、SecureBoost and so on.

Data IO module accepts the following input data format and transforms them to desired output Table.

:dense input format: input Table's value item is a list of single element, e.g.
   ::
       
      1.0,2.0,3.0,4.5
      1.1,2.1,3.4,1.3
      2.4,6.3,1.5,9.0

:svm-light input format: first item of input Table's value is label, following by a list of complex "feature_id:value" items, e.g.
   ::

      1 1:0.5 2:0.6
      0 1:0.7 3:0.8 5:0.2

:tag input format: the input Table's value is a list of tag, data io module first aggregates all tags occurred in input table, then changes all input line to one-hot representation in sorting the occurred tags by lexicographic order, e.g. assume values is
   ::

      a c
      a b d

   after processing, the new values became:
   ::

      1 0 1 0
      1 1 0 1

:tag\:value input format: the input Table's value is a list of tag:value, like a mixed svm-light and tag input-format. data io module first aggregates all tags occurred in input table, then changes all input line to one-hot representation in sorting the occurred tags by lexicographic order, then fill the occur item with value. e.g. assume values is
   ::

      a:0.2 c:1.5
      a:0.3 b:0.6 d:0.7

   after processing, the new values became:
   ::

      0.2 0 0.5 0
      0.3 0.6 0 0.7
    

Param
------

.. automodule:: federatedml.param.dataio_param
   :members:


Other Features of DataIO
------------------------

- Missing value impute, provides ["mean", "designated", "min", "max"] methods to impute missing value
- Outlier value replace, also provides several outlier replace method like missing value impute.

Please check out federatedmd/feature/imputer.py for more details.

.. literalinclude:: ../feature/imputer.py
   :caption: "__init__ of class Imputer"
   :language: python
   :linenos:
   :pyobject: Imputer.__init__

Sample Weight
=============

Sample Weight assigns weight to input sample.
Weight may be specified by input param ``class_weight`` or ``sample_weight_name``.
Output data instances will each have a weight value,
which will be used for training. While weighted instances
may be used for prediction(SampleWeight component will assign weights to instances if
prediction pipeline includes this component),
Evaluation currently does not take weights into account when calculating metrics.

If result weighted instances include negative weight, a warning message will be given.

Please note that when weight is not None, only ``weight_diff`` convergence check method may be used for training GLM.

How to Use
----------

:params:

    :class_weight: str or dict, class weight dictionary or class weight computation mode. String value only accepts 'balanced'. If dict provided, key should be class(label), and weight will not be normalized.

    :sample_weight_name: str, name of column which specifies sample weight. Extracted weight values will be normalized.

    :normalize: bool, default False. Whether to normalize sample weight extracted from `sample_weight_name` column

    :need_run: bool, whether to run this module or not

    .. Note::

        If both ``class_weight`` and ``sample_weight_name`` are provided, values from column of ``sample_weight_name`` will be used.