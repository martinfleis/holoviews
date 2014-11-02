"""
The interface subpackage provides View and Plot types to wrap external
objects with. Currently only a Pandas compatibility wrapper is
provided, which allows integrating Pandas DataFrames within the
holoviews compositioning and animation framework. Additionally, it
provides methods to apply operations to the underlying data and
convert it to standard holoviews View types.
"""

from __future__ import absolute_import

from collections import defaultdict, OrderedDict

try:
    import pandas as pd
except:
    pd = None

import param

from ..core import Dimension, NdMapping, View, Layer, Overlay, ViewMap, GridLayout, Grid
from ..core.options import options, PlotOpts
from ..view import HeatMap, ItemTable


class DataFrameView(Layer):
    """
    DataFrameView provides a convenient compatibility wrapper around
    Pandas DataFrames. It provides several core functions:

        * Allows integrating several Pandas plot types with the
          holoviews plotting system (includes plot, boxplot, histogram
          and scatter_matrix).

        * Provides several convenient wrapper methods to apply
          DataFrame methods and slice data. This includes:

              1) The apply method, which takes the DataFrame method to
                 be applied as the first argument and passes any
                 supplied args or kwargs along.

              2) The select and __getitem__ method which allow for
                 selecting and slicing the data using NdMapping.
    """

    plot_type = param.ObjectSelector(default=None, 
                                     objects=['plot', 'boxplot',
                                              'hist', 'scatter_matrix',
                                              'autocorrelation_plot',
                                              None],
                                     doc="""Selects which Pandas plot type to use,
                                            when visualizing the View.""")

    x = param.String(doc="""Dimension to visualize along the x-axis.""")

    y = param.String(doc="""Dimension to visualize along the y-axis.""")

    value = param.ClassSelector(class_=(str, Dimension), precedence=-1,
                                doc="DataFrameView has no value dimension.")

    def __init__(self, data, dimensions=None, **params):
        if pd is None:
            raise Exception("Pandas is required for the Pandas interface.")
        if not isinstance(data, pd.DataFrame):
            raise Exception('DataFrame View type requires Pandas dataframe as data.')
        if dimensions is None:
            dims = list(data.columns)
        else:
            dims = ['' for i in range(len(data.columns))]
            for dim in dimensions:
                dim_name = dim.name if isinstance(dim, Dimension) else dim
                if dim_name in data.columns:
                    dims[list(data.columns).index(dim_name)] = dim

        self._xlim = None
        self._ylim = None
        View.__init__(self, data, dimensions=dims, **params)
        self.data.columns = self.dimension_labels


    def __getitem__(self, key):
        """
        Allows slicing and selecting along the DataFrameView dimensions.
        """
        if key is ():
            return self
        else:
            if len(key) <= self.ndims:
                return self.select(**dict(zip(self.dimension_labels, key)))
            else:
                raise Exception('Selection contains %d dimensions, DataFrameView '
                                'only has %d dimensions.' % (self.ndims, len(key)))


    def select(self, **select):
        """
        Allows slice and select individual values along the DataFrameView
        dimensions. Supply the dimensions and values or slices as
        keyword arguments.
        """
        df = self.data
        for dim, k in select.items():
            if isinstance(k, slice):
                df = df[(k.start < df[dim]) & (df[dim] < k.stop)]
            else:
                df = df[df[dim] == k]
        return self.clone(df)


    def apply(self, name, *args, **kwargs):
        """
        Applies the Pandas dframe method corresponding to the supplied
        name with the supplied args and kwargs.
        """
        return self.clone(getattr(self.data, name)(*args, **kwargs))


    def dframe(self):
        """
        Returns a copy of the internal dframe.
        """
        return self.data.copy()


    def _split_dimensions(self, dimensions, ndmapping_type=NdMapping):
        invalid_dims = list(set(dimensions) - set(self.dimension_labels))
        if invalid_dims:
            raise Exception('Following dimensions could not be found %s.'
                            % invalid_dims)

        ndmapping = ndmapping_type(None, dimensions=[self.dim_dict[d] for d in dimensions])
        view_dims = set(self.dimension_labels) - set(dimensions)
        view_dims = [self.dim_dict[d] for d in view_dims]
        for k, v in self.data.groupby(dimensions):
            ndmapping[k] = self.clone(v.drop(dimensions, axis=1),
                                      dimensions=view_dims)
        return ndmapping


    def overlay_dimensions(self, dimensions):
        return self._split_dimensions(dimensions, Overlay)


    def grid(self, dimensions=[], layout=False, cols=4):
        """
        Splits the supplied the dimensions out into a Grid.
        """
        if len(dimensions) > 2:
            raise Exception('Grids hold a maximum of two dimensions.')
        if layout:
            ndmapping = self._split_dimensions(dimensions, NdMapping)
            for keys, vmap in ndmapping._data.items():
                label = ', '.join([d.pprint_value(k) for d, k in
                                   zip(ndmapping.dimensions, keys)])
                vmap.title = ' '.join([label, vmap.title])
            return GridLayout(ndmapping).cols(cols)
        return self._split_dimensions(dimensions, Grid)


    def viewmap(self, dimensions=[]):
        """
        Splits the supplied dimensions out into a ViewMap.
        """
        return self._split_dimensions(dimensions, ViewMap)

    @property
    def xlabel(self):
        return self.x

    @property
    def ylabel(self):
        return self.y

    @property
    def xlim(self):
        if self._xlim:
            return self._xlim
        if self.x:
            xdata = self.data[self.x]
            return min(xdata), max(xdata)
        else:
            return None

    @property
    def ylim(self):
        if self._ylim:
            return self._ylim
        elif self.y:
            ydata = self.data[self.y]
            return min(ydata), max(ydata)
        else:
            return None



class DFrame(DataFrameView):
    """
    DFrame is a DataFrameView type, which additionally provides
    methods to convert Pandas DataFrames to different View types,
    currently including Tables and HeatMaps.
    """

    def _create_table(self, temp_dict, value_dim, dims):
        dimensions = [self.dim_dict.get(d, d) for d in dims] if dims else {}
        label = self.label + (' - ' if self.label else '') + value_dim
        return ItemTable(temp_dict, value=value_dim, dimensions=dimensions,
                     label=label)


    def _create_heatmap(self, temp_dict, value_dim, dims):
        label = self.label + (' - ' if self.label else '') + value_dim
        dimensions = [self.dim_dict.get(d, d) for d in dims]
        return HeatMap(temp_dict, label=label, dimensions=dimensions,
                       value=self.dim_dict[value_dim])


    def _export_dataview(self, value_dim='', indices=[], reduce_fn=None,
                         view_dims=[], map_dims=[], view_method=None):
        """
        The core conversion method from the Pandas DataFrame to a View
        or Map type. The value_dim specifies the column in the
        DataFrame to select, additionally indices or a reduce_fn can
        be supplied to select or reduce multiple entries in the
        DataFrame. Further, the view_dims and map_dims determine
        which Dimensions will be grouped and supplied to the appropriate
        view_method and ViewMap respectively.
        """

        # User error checking
        selected_dims = [value_dim]+view_dims+map_dims
        for dim in selected_dims:
            if dim not in self.dimension_labels:
                raise Exception("DataFrameView has no Dimension %s." % dim)

        # Filtering out unselected dimensions
        filter_dims = list(set(self.dimension_labels) - set(selected_dims))        
        df = self.data.filter(selected_dims) if filter_dims else self.dframe()

        # Set up for View and Map dimension splitting operations
        view_dimensions = view_dims
        if map_dims:
            map_dfs = df.groupby(map_dims)
            vmap = ViewMap(None, dimensions=[self.dim_dict[d] for d in map_dims])
        else:
            map_dfs = [(None, df)]
            vmap = {}

        # Iterating over vmap elements
        for map_key, map_group in map_dfs:
            # Apply reduction function
            if reduce_fn:
                # Find indices for value and View dimensions
                cols = list(map_group.columns)
                val_idx = cols.index(value_dim)
                vdim_inds = [cols.index(d) for d in view_dims]

                # Iterate over rows and collate the result.
                temp_dict = defaultdict(list)
                for row in map_group.values:
                    if view_dims:
                        key = tuple((row[ind] for ind in vdim_inds))
                    else:
                        key = value_dim
                    temp_dict[key].append(row[val_idx])
                temp_dict = {k:reduce_fn(v) for k, v in temp_dict.items()}
            # Select values by indices
            else:
                temp_dict = OrderedDict()
                # If the selected dimensions values are not unique add Index
                if not len(indices) == 1:
                    indices = indices if indices else list(map_group.index)
                    view_dimensions = ['Index'] + view_dims
                
                # Get data from the DataFrame
                view_groups = map_group.groupby(view_dims) if view_dims else [((), map_group)]
                for k, view_group in view_groups:
                    for ind in indices:
                        if view_dims:
                            key = tuple(k)
                            if not len(indices) == 1:
                                key = (ind,) + key
                            key = key if len(key) > 1 else key[0]
                        else:
                            key = '_'.join([ind, value_dim])
                        temp_dict[key] = view_group.loc[ind, value_dim]
            vmap[map_key] = view_method(temp_dict, value_dim, view_dimensions)
        if map_dims:
            return vmap
        else:
            return vmap[None]


    def table(self, value_dim, indices=[], reduce_fn=None, dims=[], map_dims=[]):
        """
        Conversion method from DataFrame to holoviews table. Requires
        a value_dimension to be specified. Optionally a list indices
        or a reduce_fn can be specified to select or reduce multiple
        entries. Finally view_dims and map_dims can be specified to
        be inserted into the ItemTable and ViewMap respectively.  If
        not map_dims are specified a single ItemTable will be returned.
        """
        return self._export_dataview(value_dim, indices, reduce_fn,
                                     dims, map_dims, self._create_table)


    def heatmap(self, value_dim, dims, index=None, reduce_fn=None, map_dims=[]):
        """
        Conversion method from DataFrame to holoviews
        HeatMap. Requires a value_dim, the HeatMap dims and either a
        single index or a reduce_fn, to ensure there's only one value
        returned. Optionally map_dims can be specified to map the
        HeatMap over.
        """
        indices = [index] if index else []
        if 1 > len(dims) > 2:
            raise Exception("HeatMap supports either one or two dimensions")
        return self._export_dataview(value_dim, indices, reduce_fn, dims,
                                     map_dims, self._create_heatmap)


options.DFrameView = PlotOpts()
