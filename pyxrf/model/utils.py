import numpy as np
import scipy
import time as ttime
from skbeam.core.constants import XrfElement as Element
from skbeam.core.fitting.xrf_model import K_LINE, L_LINE, M_LINE

import logging
logger = logging.getLogger()


# =================================================================================
#  The following set of functions are separated from the rest of the program
#  and prepared to be moved to scikit-beam (skbeam.core.fitting.xrf_model)


def grid_interpolate(data, xx, yy, xx_uniform=None, yy_uniform=None):
    """
    Interpolate unevenly sampled data to even grid. The new even grid has the same
    dimensions as the original data and covers full range of original X and Y axes.

    Parameters
    ----------

    data : ndarray
        2D array with data values (`xx`, `yy` and `data` must have the same shape)
        ``data`` may be None. In this case interpolation will not be performed, but uniform
        grid will be generated. Use this feature to generate uniform grid.
    xx : ndarray
        2D array with measured values of X coordinates of data points (the values may be unevenly spaced)
    yy : ndarray
        2D array with measured values of Y coordinates of data points (the values may be unevenly spaced)
    xx_uniform : ndarray
        2D array with evenly spaced X axis values (same shape as `data`). If not provided, then
        generated automatically and returned by the function.
    yy_uniform : ndarray
        2D array with evenly spaced Y axis values (same shape as `data`). If not provided, then
        generated automatically and returned by the function.

    Returns
    -------
    data_uniform : ndarray
        2D array with data fitted to even grid (same shape as `data`)
    xx_uniform : ndarray
        2D array with evenly spaced X axis values (same shape as `data`)
    yy_uniform : ndarray
        2D array with evenly spaced Y axis values (same shape as `data`)
    """

    # Check if data shape and shape of coordinate arrays match
    if data is not None:
        if data.shape != xx.shape:
            msg = "Shapes of data and coordinate arrays do not match. "\
                  "(function 'grid_interpolate')"
            raise ValueError(msg)
    if xx.shape != yy.shape:
        msg = "Shapes of coordinate arrays 'xx' and 'yy' do not match. "\
              "(function 'grid_interpolate')"
        raise ValueError(msg)
    if (xx_uniform is not None) and (xx_uniform.shape != xx.shape):
        msg = "Shapes of data and array of uniform coordinates 'xx_uniform' do not match. "\
              "(function 'grid_interpolate')"
        raise ValueError(msg)
    if (yy_uniform is not None) and (xx_uniform.shape != xx.shape):
        msg = "Shapes of data and array of uniform coordinates 'yy_uniform' do not match. "\
              "(function 'grid_interpolate')"
        raise ValueError(msg)

    ny, nx = xx.shape
    # Data must be 2-dimensional to use the following interpolation procedure.
    if (nx <= 1) or (ny <= 1):
        logger.debug("Function utils.grid_interpolate: single row or column scan. "
                     "Grid interpolation is skipped")
        return data, xx, yy

    def _get_range(vv):
        """
        Returns the range of the data coordinates along X or Y axis. Coordinate
        data for a single axis is represented as a 2D array ``vv``. The array
        will have all rows or all columns identical or almost identical.
        The range is returned as ``vv_min`` (leftmost or topmost value)
        and ``vv_max`` (rightmost or bottommost value). Note, that ``vv_min`` may
        be greater than ``vv_max``

        Parameters
        ----------
        vv : ndarray
            2-d array of coordinates

        Returns
        -------
        vv_min : float
            starting point of the range
        vv_max : float
            end of the range
        """
        # The assumption is that X values are mostly changing along the dimension 1 and
        #   Y values change along the dimension 0 of the 2D array and only slightly change
        #   along the alternative dimension. Determine, if the range is for X or Y
        #   axis based on the dimension in which value change is the largest.
        if abs(vv[0, 0] - vv[0, -1]) > abs(vv[0, 0] - vv[-1, 0]):
            vv_min = np.median(vv[:, 0])
            vv_max = np.median(vv[:, -1])
        else:
            vv_min = np.median(vv[0, :])
            vv_max = np.median(vv[-1, :])

        return vv_min, vv_max

    if xx_uniform is None or yy_uniform is None:
        # Find the range of axes
        x_min, x_max = _get_range(xx)
        y_min, y_max = _get_range(yy)
        _yy_uniform, _xx_uniform = np.mgrid[y_min: y_max: ny * 1j, x_min: x_max: nx * 1j]

    if xx_uniform is None:
        xx_uniform = _xx_uniform
    if yy_uniform is None:
        yy_uniform = _yy_uniform

    xx = xx.flatten()
    yy = yy.flatten()
    xxyy = np.stack((xx, yy)).T

    if data is not None:
        # Do the interpolation only if data is provided
        data = data.flatten()
        # Do the interpolation
        data_uniform = scipy.interpolate.griddata(xxyy, data, (xx_uniform, yy_uniform),
                                                  method='linear', fill_value=0)
    else:
        data_uniform = None

    return data_uniform, xx_uniform, yy_uniform


def normalize_data_by_scaler(data_in, scaler, *, data_name=None, name_not_scalable=None):
    '''
    Normalize data based on the availability of scaler

    Parameters
    ----------

    data_in : ndarray
        numpy array of input data
    scaler : ndarray
        numpy array of scaling data, the same size as data_in
    data_name : str
        name of the data set ('time' or 'i0' etc.)
    name_not_scalable : list
        names of not scalable datasets (['time', 'i0_time'])

    Returns
    -------
    ndarray with normalized data, the same shape as data_in
        The returned array is the reference to 'data_in' if no normalization
        is applied to data or reference to modified copy of 'data_in' if
        normalization was applied.

    ::note::

        Normalization will not be performed if the following is true:

        - scaler is None

        - scaler is not the same shape as data_in

        - scaler contains all elements equal to zero

        If normalization is not performed then REFERENCE to data_in is returned.

    '''

    if data_in is None or scaler is None:  # Nothing to scale
        logger.debug("Function utils.gnormalize_data_by_scaler: data and/or scaler arrays are None. "
                     "Data scaling is skipped.")
        return data_in

    if data_in.shape != scaler.shape:
        logger.debug("Function utils.gnormalize_data_by_scaler: data and scaler arrays have different shape. "
                     "Data scaling is skipped.")
        return data_in

    do_scaling = False
    # Check if data name is in the list of non-scalable items
    # If data name or the list does not exits, then do the scaling
    if name_not_scalable is None or \
            data_name is None or \
            data_name not in name_not_scalable:
        do_scaling = True

    # If scaler is all zeros, then don't scale the data:
    #   check if there is at least one nonzero element
    n_nonzero = np.count_nonzero(scaler)
    if not n_nonzero:
        logger.debug("Function utils.gnormalize_data_by_scaler: scaler is all-zeros array. "
                     "Data scaling is skipped.")
        do_scaling = False

    if do_scaling:
        # If scaler contains some zeros, set those zeros to mean value
        if data_in.size != n_nonzero:
            s_mean = np.mean(scaler[scaler != 0])
            # Avoid division by very small number (or zero)
            if np.abs(s_mean) < 1e-10:
                s_mean = 1e-10 if np.sign(s_mean) >= 0 else -1e-10
            scaler = scaler.copy()
            scaler[scaler == 0.0] = s_mean
        data_out = data_in / scaler
    else:
        data_out = data_in

    return data_out


def fitting_admm(data, ref_spectra, *, rate=0.2, maxiter=50, epsilon=1e-30):


    assert ref_spectra.ndim == 2, "The array 'ref_spectra' must have 2 dimensions"

    n_pts = data.shape[0]
    data_dims = data.shape[1:]
    n_pts_2 = ref_spectra.shape[0]
    n_refs = ref_spectra.shape[1]

    assert n_pts == n_pts_2, f"ADMM fitting: number of spectrum points in data ({n_pts}) "\
                             f"and references ({n_pts_2}) do not match."

    assert rate > 0.0, f"ADMM fitting: parameter 'rate' is zero or negative ({rate:.6g})"

    assert maxiter > 0, f"ADMM fitting: parameter 'maxiter' is zero or negative ({rate})"

    assert epsilon > 0.0, f"ADMM fitting: parameter 'epsilon' is zero or negative ({rate:.6g})"

    # Depending on 'data_dim', there could be three cases
    #   'data_dim' is empty - data is 1D array representing a single point, 1D array of weights
    #                         will be returned, data must be converted to 2D array for processing
    #   'data_dim' has one element - data is 2D array, representing one line of pixels, process as is
    #   'data_dim' has more than one element - data is multidimensional array representing
    #                        multidimensional image, reshape to 1D data (2D array) for processing
    #                        and the convert back to multidimensional representation

    if not data_dims:
        data_1D = np.expand_dims(data, axis=1)
    elif len(data_dims) > 1:
        data_1D = np.reshape(data, [n_pts, np.prod(data_dims)])
    else:
        data_1D = data

    _, n_pixels = data_1D.shape

    y = data_1D
    # Calculate some quantity to be used in the iteration
    A = ref_spectra
    At = np.transpose(A)

    z = np.matmul(At, y)
    c = np.matmul(At, A)

    # Initialize variables
    w = np.ones(shape=[n_refs, n_pixels])
    u = np.zeros(shape=[n_refs, n_pixels])

    # Feasibility test: x == w
    convergence = np.zeros(shape=[maxiter])
    feasibility = np.zeros(shape=[maxiter])

    dg = np.eye(n_refs, dtype=float) * rate
    m1 = np.linalg.inv((c + dg))

    n_iter = 0
    for i in range(maxiter):
        m2 = z + (w-u) * rate
        x = np.matmul(m1, m2)
        w_updated = x + u
        w_updated = w_updated.clip(min=0)
        u = u + x - w_updated

        conv = np.linalg.norm(w_updated - w) / np.linalg.norm(w_updated)
        convergence[i] = conv
        feasibility[i] = np.linalg.norm(x - w_updated)

        w = w_updated

        if conv < epsilon:
            n_iter = i + 1
            break

    if not data_dims:
        w = np.squeeze(w, axis=1)
    elif len(data_dims) > 1:
        w = np.reshape(w, np.insert(data_dims, 0, n_refs))

    convergence = convergence[:n_iter]
    feasibility = feasibility[:n_iter]

    return w, convergence, feasibility

# ===============================================================================

# ===============================================================================
# The following functions are prepared to be moved to scikit-beam

def _get_2_sqrt_2_log2():
    return 2 * np.sqrt(2 * np.log(2))


def gaussian_sigma_to_fwhm(sigma):
    """
    Converts parameters of Gaussian curve: 'sigma' to 'fwhm'

    Parameters
    ----------

    sigma : float
        sigma of the Gaussian curve

    Returns
    -------
    FWHM of the Gaussian curve
    """
    return sigma * _get_2_sqrt_2_log2()


def gaussian_fwhm_to_sigma(fwhm):
    """
    Converts parameters of Gaussian curve: 'fwhm' to 'sigma'

    Parameters
    ----------

    fwhm : float
        Full Width at Half Maximum of the Gaussian curve

    Returns
    -------
    sigma of the Gaussian curve
    """
    return fwhm / _get_2_sqrt_2_log2()


def _get_sqrt_2_pi():
    return np.sqrt(2 * np.pi)


def gaussian_max_to_area(peak_max, peak_sigma):
    """
    Computes the area under Gaussian curve based on maximum and sigma

    Parameters
    ----------

    peak_max : float
        maximum of the Gaussian curve
    peak_sigma : float
        sigma of the Gaussian curve

    Returns
    -------
    area under the Gaussian curve
    """
    return peak_max * peak_sigma * _get_sqrt_2_pi()


def gaussian_area_to_max(peak_area, peak_sigma):
    """
    Computes the maximum of the Gaussian curve based on area
    under the curve and sigma

    Parameters
    ----------

    peak_area : float
       area under the Gaussian curve
    peak_sigma : float
        sigma of the Gaussian curve

    Returns
    -------
    area under the Gaussian curve
    """
    if peak_sigma == 0:
        return 0
    else:
        return peak_area / peak_sigma / _get_sqrt_2_pi()


def get_full_eline_list():
    """
    Returns the list of the emission lines supported by ``scikit-beam``
    """
    eline_list = K_LINE + L_LINE + M_LINE
    return eline_list


def check_eline_name(eline_name):
    """
    Check if the emission line name is in the list of supported names.
    Emission name must be in the format: K_K, Fe_K etc. The list includes K, L and M lines.
    The function is case-sensitive.

    Parameters
    ----------
    eline_name : str
        name of the emission line (K_K, Fe_K etc. for valid emission line). In general
        the string may contain arbitrary sequence characters, may be empty or None. The
        function will return True only if the sequence represents emission line from
        the list of supported emission lines.

    Returns
        True if ``eline_name`` is in the list of supported emission lines, False otherwise
    """
    if not eline_name or not isinstance(eline_name, str):
        return False

    if eline_name in get_full_eline_list():
        return True
    else:
        return False


def check_if_eline_is_activated(elemental_line, incident_energy):
    """
    Checks if emission line is activated at given incident beam energy

    Parameters
    ----------

    elemental_line : str
        emission line in the format K_K or Fe_K
    incident_energy : float
        incident energy in keV

    Returns
    -------
        bool value, indicating if the emission line is activated
    """
    element = elemental_line.split('_')[0]
    e = Element(element)
    if e.cs(incident_energy)['ka1'] == 0:
        return False
    else:
        return True


# ==================================================================================


def convert_time_to_nexus_string(t):
    """
    Convert time to a string according to NEXUS format

    Parameters
    ----------

    t : time.struct_time
        Time in the format returned by ``time.localtime`` or ``time.gmtime``

    Returns
    -------

    t : str
        A string represetation of time according to NEXUS standard
    """
    # Convert to sting format recommented for NEXUS files
    t = ttime.strftime("%Y-%m-%dT%H:%M:%S+00:00", t)
    return t


def convert_time_from_nexus_string(t):
    """
    Convert time from NEXUS string to ``time.struct_time``

    Parameters
    ----------

    t : str
        A string represetation of time according to NEXUS standard

    Returns
    -------

    t : time.struct_time
        Time in the format returned by ``time.localtime`` or ``time.gmtime``
    """
    # Convert to sting format recommented for NEXUS files
    t = ttime.strptime(t, "%Y-%m-%dT%H:%M:%S+00:00")
    return t
