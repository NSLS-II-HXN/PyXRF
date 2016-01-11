# ######################################################################
# Copyright (c) 2014, Brookhaven Science Associates, Brookhaven        #
# National Laboratory. All rights reserved.                            #
#                                                                      #
# Redistribution and use in source and binary forms, with or without   #
# modification, are permitted provided that the following conditions   #
# are met:                                                             #
#                                                                      #
# * Redistributions of source code must retain the above copyright     #
#   notice, this list of conditions and the following disclaimer.      #
#                                                                      #
# * Redistributions in binary form must reproduce the above copyright  #
#   notice this list of conditions and the following disclaimer in     #
#   the documentation and/or other materials provided with the         #
#   distribution.                                                      #
#                                                                      #
# * Neither the name of the Brookhaven Science Associates, Brookhaven  #
#   National Laboratory nor the names of its contributors may be used  #
#   to endorse or promote products derived from this software without  #
#   specific prior written permission.                                 #
#                                                                      #
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS  #
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT    #
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS    #
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE       #
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,           #
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES   #
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR   #
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)   #
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,  #
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OTHERWISE) ARISING   #
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE   #
# POSSIBILITY OF SUCH DAMAGE.                                          #
########################################################################
from __future__ import absolute_import
__author__ = 'Li Li'

import numpy as np
import time
import copy
import six
import os
from collections import OrderedDict
import multiprocessing
import h5py
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import json
from scipy.optimize import nnls
from scipy.interpolate import interp1d, interp2d

from enaml.qt.qt_application import QApplication

from atom.api import Atom, Str, observe, Typed, Int, List, Dict, Float, Bool
from skbeam.core.fitting.xrf_model import (
    ModelSpectrum, update_parameter_dict, sum_area, set_parameter_bound,
    ParamController, K_LINE, L_LINE, M_LINE, nnls_fit, trim,
    construct_linear_model, linear_spectrum_fitting, register_strategy,
    TRANSITIONS_LOOKUP, fit_per_line_nnls)
from skbeam.core.fitting.background import snip_method
from skbeam.fluorescence import XrfElement as Element
from .guessparam import (calculate_profile, fit_strategy_list,
                         trim_escape_peak, define_range, get_energy,
                         get_Z, PreFitStatus, ElementController,
                         update_param_from_element)
from .fileio import read_hdf_APS, output_data, flip_data

#from lmfit import fit_report
import lmfit

import pickle

import logging
logger = logging.getLogger(__name__)


class Fit1D(Atom):
    """
    Fit 1D fluorescence spectrum. Users can choose multiple strategies
    for this fitting.
    """
    file_status = Str()
    default_parameters = Dict()
    param_dict = Dict()

    element_list = List()

    data_all = Typed(np.ndarray)
    data = Typed(np.ndarray)
    fit_x = Typed(np.ndarray)
    fit_y = Typed(np.ndarray)
    residual = Typed(np.ndarray)
    comps = Dict()
    fit_strategy1 = Int(0)
    fit_strategy2 = Int(0)
    fit_strategy3 = Int(0)
    fit_strategy4 = Int(0)
    fit_strategy5 = Int(0)
    fit_result = Typed(object)
    data_title = Str()

    working_directory = Str()
    result_folder = Str()

    all_strategy = Typed(object)

    x0 = Typed(np.ndarray)
    y0 = Typed(np.ndarray)
    bg = Typed(np.ndarray)
    es_peak = Typed(np.ndarray)
    cal_x = Typed(np.ndarray)
    cal_y = Typed(np.ndarray)
    cal_spectrum = Dict()

    # attributes used by the ElementEdit window
    #selected_element = Str()
    selected_index = Int()
    elementinfo_list = List()

    function_num = Int(0)
    nvar = Int(0)
    chi2 = Float(0.0)
    red_chi2 = Float(0.0)
    global_param_list = List()

    fit_num = Int(100)
    ftol = Float(1e-5)
    c_weight = Float(1e2)

    save_name = Str()
    fit_img = Dict()

    save_point = Bool(False)
    point1v = Int(0)
    point1h = Int(0)
    point2v = Int(0)
    point2h = Int(0)

    EC = Typed(object)
    result_dict_names = List()
    e_name = Str()
    add_element_intensity = Float(100.0)
    pileup_data = Dict()

    raise_bg = Float(0.0)
    pixel_bin = Int(0)
    linear_bg = Bool(False)
    use_snip = Bool(True)
    bin_energy = Int(0)
    fit_info = Str()
    pixel_fit_info = Str()
    save_tiff = Bool(False)
    save_txt = Bool(False)

    pixel_fit_method = Int(0)

    def __init__(self, *args, **kwargs):
        self.working_directory = kwargs['working_directory']
        self.result_folder = kwargs['working_directory']
        self.default_parameters = kwargs['default_parameters']
        self.param_dict = copy.deepcopy(self.default_parameters)
        self.all_strategy = OrderedDict()

        self.EC = ElementController()
        self.pileup_data = {'element1': 'Si_K',
                            'element2': 'Si_K',
                            'intensity': 100.0}

        # plotting purposes
        self.fit_strategy1 = 0
        self.fit_strategy2 = 0
        self.fit_strategy1 = 1
        self.fit_strategy2 = 4

    def result_folder_changed(self, change):
        """
        Observer function to be connected to the fileio model
        in the top-level gui.py startup

        Parameters
        ----------
        changed : dict
            This is the dictionary that gets passed to a function
            with the @observe decorator
        """
        self.result_folder = change['value']

    def data_title_update(self, change):
        """
        Observer function to be connected to the fileio model
        in the top-level gui.py startup

        Parameters
        ----------
        changed : dict
            This is the dictionary that gets passed to a function
            with the @observe decorator
        """
        self.data_title = change['value']

    @observe('selected_index')
    def _selected_element_changed(self, change):
        if change['value'] > 0:
            selected_element = self.element_list[change['value']-1]
            if len(selected_element) <= 4:
                element = selected_element.split('_')[0]
                self.elementinfo_list = sorted([e for e in self.param_dict.keys()
                                                if (element+'_' in e) and  # error between S_k or Si_k
                                                ('pileup' not in e)])  # Si_ka1 not Si_K
            else:
                element = selected_element  # for pileup peaks
                self.elementinfo_list = sorted([e for e in self.param_dict.keys()
                                                if element.replace('-', '_') in e])

    def read_param_from_file(self, param_path):
        """
        Update parameters if new param_path is given.

        Parameters
        ----------
        param_path : str
            path to save the file
        """
        with open(param_path, 'r') as json_data:
            self.default_parameters = json.load(json_data)

    def update_default_param(self, param):
        """assigan new values to default param.

        Parameters
        ----------
        param : dict
        """
        self.default_parameters = param

    def apply_default_param(self):
        self.param_dict = copy.deepcopy(self.default_parameters)
        element_list = self.param_dict['non_fitting_values']['element_list']
        self.element_list = [e.strip(' ') for e in element_list.split(',')]

        # show the list of elements on add/remove window
        self.EC.delete_all()
        self.create_EC_list(self.element_list)
        self.update_name_list()

        # global parameters
        # for GUI purpose only
        # if we do not clear the list first, there is not update on the GUI
        self.global_param_list = []
        self.global_param_list = sorted([k for k in six.iterkeys(self.param_dict)
                                         if k == k.lower() and k != 'non_fitting_values'])

        self.define_range()

        # register the strategy and extend the parameter list
        # to cover all given elements
        #for strat_name in fit_strategy_list:
        #    strategy = extract_strategy(self.param_dict, strat_name)
            # register the strategy and extend the parameter list
            # to cover all given elements
        #    register_strategy(strat_name, strategy)
            #set_parameter_bound(self.param_dict, strat_name)

        # define element_adjust as fixed
        #self.param_dict = define_param_bound_type(self.param_dict)

    def exp_data_update(self, change):
        """
        Observer function to be connected to the fileio model
        in the top-level gui.py startup

        Parameters
        ----------
        changed : dict
            This is the dictionary that gets passed to a function
            with the @observe decorator
        """
        self.data = np.asarray(change['value'])

    def exp_data_all_update(self, change):
        """
        Observer function to be connected to the fileio model
        in the top-level gui.py startup

        Parameters
        ----------
        changed : dict
            This is the dictionary that gets passed to a function
            with the @observe decorator
        """
        self.data_all = np.asarray(change['value'])

    def filename_update(self, change):
        """
        Observer function to be connected to the fileio model
        in the top-level gui.py startup

        Parameters
        ----------
        changed : dict
            This is the dictionary that gets passed to a function
            with the @observe decorator
        """
        self.save_name = change['value']

    @observe('fit_strategy1')
    def update_strategy1(self, change):
        self.all_strategy.update({'strategy1': change['value']})
        if change['value']:
            logger.info('Strategy at step 1 is: {}'.
                        format(fit_strategy_list[change['value']-1]))

    @observe('fit_strategy2')
    def update_strategy2(self, change):
        self.all_strategy.update({'strategy2': change['value']})
        if change['value']:
            logger.info('Strategy at step 2 is: {}'.
                        format(fit_strategy_list[change['value']-1]))

    @observe('fit_strategy3')
    def update_strategy3(self, change):
        self.all_strategy.update({'strategy3': change['value']})
        if change['value']:
            logger.info('Strategy at step 3 is: {}'.
                        format(fit_strategy_list[change['value']-1]))

    @observe('fit_strategy4')
    def update_strategy4(self, change):
        self.all_strategy.update({'strategy4': change['value']})
        if change['value']:
            logger.info('Strategy at step 4 is: {}'.
                        format(fit_strategy_list[change['value']-1]))

    @observe('fit_strategy5')
    def update_strategy5(self, change):
        self.all_strategy.update({'strategy5': change['value']})
        if change['value']:
            logger.info('Strategy at step 5 is: {}'.
                        format(fit_strategy_list[change['value']-1]))

    def update_param_with_result(self):
        update_parameter_dict(self.param_dict, self.fit_result)

    def define_range(self):
        """
        Cut x range according to values define in param_dict.
        """
        lowv = self.param_dict['non_fitting_values']['energy_bound_low']['value']
        highv = self.param_dict['non_fitting_values']['energy_bound_high']['value']
        self.x0, self.y0 = define_range(self.data, lowv, highv,
                                        self.param_dict['e_offset']['value'],
                                        self.param_dict['e_linear']['value'])

    def get_background(self):
        self.bg = snip_method(self.y0,
                              self.param_dict['e_offset']['value'],
                              self.param_dict['e_linear']['value'],
                              self.param_dict['e_quadratic']['value'],
                              width=self.param_dict['non_fitting_values']['background_width'])

    def get_profile(self):
        """
        Calculate profile based on current parameters.
        """
        #self.define_range()
        self.cal_x, self.cal_spectrum, area_dict = calculate_profile(self.x0,
                                                                     self.y0,
                                                                     self.param_dict,
                                                                     self.element_list)
        # add escape peak
        if self.param_dict['non_fitting_values']['escape_ratio'] > 0:
            self.cal_spectrum['escape'] = trim_escape_peak(self.data,
                                                           self.param_dict,
                                                           len(self.y0))

        self.cal_y = np.zeros(len(self.cal_x))
        for k, v in six.iteritems(self.cal_spectrum):
            self.cal_y += v

        self.residual = self.cal_y - self.y0

    def fit_data(self, x0, y0):
        fit_num = self.fit_num
        ftol = self.ftol
        c_weight = 1  #avoid zero point
        MS = ModelSpectrum(self.param_dict, self.element_list)
        MS.assemble_models()

        #weights = 1/(c_weight + np.abs(y0))
        weights = 1/np.sqrt(c_weight + np.abs(y0))
        #weights /= np.sum(weights)
        result = MS.model_fit(x0, y0,
                              weights=weights,
                              maxfev=fit_num,
                              xtol=ftol, ftol=ftol, gtol=ftol)
        self.fit_x = (result.values['e_offset'] +
                      result.values['e_linear'] * x0 +
                      result.values['e_quadratic'] * x0**2)
        self.fit_y = result.best_fit
        self.fit_result = result
        self.residual = self.fit_y - y0

    def fit_multiple(self):
        """
        Fit data in sequence according to given strategies.
        The param_dict is extended to cover elemental parameters.
        Use app.precessEvents() for multi-threading.
        """
        app = QApplication.instance()
        self.define_range()
        self.get_background()

        #PC = ParamController(self.param_dict, self.element_list)
        #self.param_dict = PC.params
        #print('param keys {}'.format(self.param_dict.keys()))

        if self.param_dict['non_fitting_values']['escape_ratio'] > 0:
            self.es_peak = trim_escape_peak(self.data,
                                            self.param_dict,
                                            self.y0.size)
            y0 = self.y0 - self.bg - self.es_peak
        else:
            y0 = self.y0 - self.bg

        t0 = time.time()
        self.fit_info = 'Summed spectrum fitting is in process.'
        app.processEvents()
        logger.info('-------- '+self.fit_info+' --------')

        for k, v in six.iteritems(self.all_strategy):
            if v:
                strat_name = fit_strategy_list[v-1]
                #self.fit_info = 'Fit with {}: {}'.format(k, strat_name)

                logger.info(self.fit_info)
                strategy = extract_strategy(self.param_dict, strat_name)
                # register the strategy and extend the parameter list
                # to cover all given elements
                register_strategy(strat_name, strategy)
                set_parameter_bound(self.param_dict, strat_name)

                self.fit_data(self.x0, y0)
                self.update_param_with_result()
                self.assign_fitting_result()
                app.processEvents()

        t1 = time.time()
        logger.warning('Time used for summed spectrum fitting is : {}'.format(t1-t0))

        # for GUI purpose only
        # if we do not clear the dict first, there is not update on the GUI
        param_temp = copy.deepcopy(self.param_dict)
        del self.param_dict['non_fitting_values']
        self.param_dict = param_temp

        self.comps.clear()
        comps = self.fit_result.eval_components(x=self.x0)
        self.comps = combine_lines(comps, self.element_list, self.bg)

        if self.param_dict['non_fitting_values']['escape_ratio'] > 0:
            self.fit_y += self.bg + self.es_peak
            self.comps['escape'] = self.es_peak
        else:
            self.fit_y += self.bg

        self.save_result()
        self.assign_fitting_result()
        self.fit_info = 'Summed spectrum fitting is done!'
        logger.info('-------- ' + self.fit_info + ' --------')

    def assign_fitting_result(self):
        self.function_num = self.fit_result.nfev
        self.nvar = self.fit_result.nvarys
        self.chi2 = np.around(self.fit_result.chisqr, 4)
        self.red_chi2 = np.around(self.fit_result.redchi, 4)

    def fit_single_pixel(self):
        """
        This function performs single pixel fitting.
        Multiprocess is considered.
        """
        app = QApplication.instance()
        raise_bg = self.raise_bg
        pixel_bin = self.pixel_bin
        comp_elastic_combine = True
        linear_bg = self.linear_bg
        use_snip = self.use_snip
        bin_energy = self.bin_energy

        create_fig = False  # save pixel fit as fig

        if self.pixel_fit_method == 0:
            pixel_fit = 'nnls'
        elif self.pixel_fit_method == 1:
            pixel_fit = 'nonlinear'

        logger.info('-------- Fitting of single pixels starts. --------')
        t0 = time.time()
        self.pixel_fit_info = 'Pixel fitting is in process.'
        app.processEvents()
        result_map, calculation_info = single_pixel_fitting_controller(self.data_all,
                                                                       self.param_dict,
                                                                       method=pixel_fit,
                                                                       pixel_bin=pixel_bin,
                                                                       raise_bg=raise_bg,
                                                                       comp_elastic_combine=comp_elastic_combine,
                                                                       linear_bg=linear_bg,
                                                                       use_snip=use_snip,
                                                                       bin_energy=bin_energy)

        t1 = time.time()
        logger.info('Time used for pixel fitting is : {}'.format(t1-t0))

        # output to .h5 file
        fpath = os.path.join(self.result_folder, self.save_name)

        # interpolation then save
        with h5py.File(fpath, 'r') as f:
            x_data = np.array(f['xrfmap/positions/pos'][0, :, :])
            y_data = np.array(f['xrfmap/positions/pos'][1, :, :])

        #x_data = flip_data(x_data)
        x_data = np.fliplr(x_data)

        rangex = x_data[0,:]
        rangey = y_data[:,0]
        start_x = rangex[0]
        start_y = rangey[0]
        #start_x = -42.631
        #start_y = 144.427
        dimv = self.data_all.shape
        logger.info('Interpolating image... ')
        for k, v in six.iteritems(result_map):
            shapev = [dimv[1], dimv[0]]  # veritcal first, then horizontal
            interp_d = interp1d_scan(shapev, rangex, rangey, start_x, start_y,
                                     x_data, y_data, v)
            interp_d[np.isnan(interp_d)] = 0
            result_map[k] = interp_d

        prefix_fname = self.save_name.split('.')[0]
        if 'ch1' in self.data_title:
            inner_path = 'xrfmap/det1'
            fit_name = prefix_fname+'_ch1_fit'
        elif 'ch2' in self.data_title:
            inner_path = 'xrfmap/det2'
            fit_name = prefix_fname+'_ch2_fit'
        elif 'ch3' in self.data_title:
            inner_path = 'xrfmap/det3'
            fit_name = prefix_fname+'_ch3_fit'
        else:
            inner_path = 'xrfmap/detsum'
            fit_name = prefix_fname+'_fit'
        save_fitdata_to_hdf(fpath, result_map, datapath=inner_path)

        # output error
        if pixel_fit == 'nonlinear':
            error_map = calculation_info['error_map']
            save_fitdata_to_hdf(fpath, error_map, datapath=inner_path,
                                data_saveas='xrf_fit_error',
                                dataname_saveas='xrf_fit_error_name')

        # Update GUI so that results can be seen immediately
        self.fit_img[fit_name] = result_map
        #self.fit_img = {k:v for k,v in six.iteritems(self.fit_img) if prefix_fname in k}

        # get fitted spectrum and save them to figs
        if self.save_point is True:
            self.pixel_fit_info = 'Saving output ...'
            app.processEvents()
            elist = calculation_info['fit_name']
            matv = calculation_info['regression_mat']
            results = calculation_info['results']
            #fit_range = calculation_info['fit_range']
            x = calculation_info['energy_axis']
            x = (self.param_dict['e_offset']['value'] +
                 self.param_dict['e_linear']['value']*x +
                 self.param_dict['e_quadratic']['value'] * x**2)
            data_fit = calculation_info['exp_data']

            p1 = [self.point1v, self.point1h]
            p2 = [self.point2v, self.point2h]

            if create_fig is True:
                output_folder = os.path.join(self.result_folder, prefix_fname+'_pixel_fit')
                if os.path.exists(output_folder) is False:
                    os.mkdir(output_folder)
                save_fitted_fig(x, matv, results[:, :, 0:len(elist)],
                                p1, p2,
                                data_fit, self.param_dict,
                                output_folder, use_sinp=use_snip)

            save_fitted_as_movie(x, matv, results[:, :, 0:len(elist)],
                                 p1, p2,
                                 data_fit, self.param_dict,
                                 self.result_folder, prefix=fit_name, use_sinp=use_snip)
            logger.info('Done with saving fitting plots.')

        if self.save_tiff:
            namelist = self.data_title.split('_')
            output_n = namelist[0]+'_'+namelist[1]+'_'+'output'
            output_data(fpath, os.path.join(self.result_folder, output_n))
        if self.save_txt:
            namelist = self.data_title.split('_')
            output_n = namelist[0]+'_'+namelist[1]+'_'+'output'
            output_data(fpath, os.path.join(self.result_folder, output_n),
                        file_format='txt')

        self.pixel_fit_info = 'Pixel fitting is done!'
        app.processEvents()
        logger.info('-------- Fitting of single pixels is done! --------')

    def save_result(self, fname=None):
        """
        Save fitting results.

        Parameters
        ----------
        fname : str, optional
            name of output file
        """
        if not fname:
            fname = self.data_title+'_out.txt'
        filepath = os.path.join(self.result_folder, fname)

        area_list = []
        for v in self.fit_result.params.keys():
            if 'ka1_area' in v or 'la1_area' in v or 'ma1_area' in v or 'amplitude' in v:
                area_list.append(v)

        with open(filepath, 'w') as myfile:
            myfile.write('\n {:<10} \t {} \t {}'.format('name', 'summed area', 'error in %'))
            for k, v in six.iteritems(self.comps):
                if k == 'background':
                    continue
                for name in area_list:
                     if k.lower() in name.lower():
                         errorv = self.fit_result.params[name].stderr/(self.fit_result.params[name].value+1e-8)
                         errorv *= 100
                         errorv = np.round(errorv, 3)
                         myfile.write('\n {:<10} \t {} \t {}'.format(k, np.round(np.sum(v), 3), str(errorv)+'%'))
            myfile.write('\n\n')
            myfile.write(lmfit.fit_report(self.fit_result, sort_pars=True))
            logger.warning('Results are saved to {}'.format(filepath))

    def update_name_list(self):
        """
        When result_dict_names change, the looper in enaml will update.
        """
        # need to clean list first, in order to refresh the list in GUI
        self.selected_index = 0
        self.elementinfo_list = []

        self.result_dict_names = []
        self.result_dict_names = self.EC.element_dict.keys()
        self.param_dict = update_param_from_element(self.param_dict,
                                                    self.EC.element_dict.keys())

        self.element_list = []
        self.element_list = self.EC.element_dict.keys()
        logger.info('The full list for fitting is {}'.format(self.element_list))

    def create_EC_list(self, element_list):
        temp_dict = OrderedDict()
        for e in element_list:
            if '-' in e:  # pileup peaks
                e1, e2 = e.split('-')
                energy = float(get_energy(e1))+float(get_energy(e2))

                ps = PreFitStatus(z=get_Z(e),
                                  energy=str(energy), norm=1)
                temp_dict[e] = ps

            else:
                ename = e.split('_')[0]
                ps = PreFitStatus(z=get_Z(ename),
                                  energy=get_energy(e),
                                  norm=1)

                temp_dict[e] = ps
        self.EC.add_to_dict(temp_dict)

    # def manual_input(self):
    #     #default_area = 1e2
    #     ps = PreFitStatus(z=get_Z(self.e_name),
    #                       energy=get_energy(self.e_name),
    #                       #area=area_dict[self.e_name]*ratio_v,
    #                       #spectrum=data_out[self.e_name]*ratio_v,
    #                       #maxv=self.add_element_intensity,
    #                       norm=1)
    #                       #lbd_stat=False)
    #
    #     self.EC.add_to_dict({self.e_name: ps})
    #     logger.info('')
    #     self.update_name_list()

    # def add_pileup(self):
    #     if self.pileup_data['intensity'] > 0:
    #         e_name = (self.pileup_data['element1'] + '-'
    #                   + self.pileup_data['element2'])
    #
    #         energy = str(float(get_energy(self.pileup_data['element1']))
    #                      + float(get_energy(self.pileup_data['element2'])))
    #
    #         ps = PreFitStatus(z=get_Z(e_name),
    #                           energy=energy,
    #                           #area=area_dict[e_name]*ratio_v,
    #                           #spectrum=data_out[e_name]*ratio_v,
    #                           #maxv=self.pileup_data['intensity'],
    #                           norm=1)
    #                           #lbd_stat=False)
    #         logger.info('{} peak is added'.format(e_name))
    #     self.EC.add_to_dict({e_name: ps})
    #     self.update_name_list()


def combine_lines(components, element_list, background):
    """
    Combine results for different lines of the same element.
    And also add background, compton and elastic.

    Parameters
    ----------
    components : dict
        output results from lmfit
    element_list : list
        list of elemental lines
    background : array
        background calculated in given range

    Returns
    -------
    dict :
        combined results for elements and other related peaks.
    """
    new_components = {}
    for e in element_list:
        if len(e) <= 4:
            e_temp = e.split('_')[0]
            intensity = 0
            for k, v in six.iteritems(components):
                if (e_temp in k) and (e not in k):
                    intensity += v
            new_components[e] = intensity
        else:
            comp_name = 'pileup_' + e.replace('-', '_') + '_'  # change Si_K-Si_K to Si_K_Si_K
            new_components[e] = components[comp_name]

    # add background and elastic
    new_components['background'] = background
    new_components['compton'] = components['compton']
    new_components['elastic'] = components['elastic_']
    return new_components


def extract_strategy(param, name):
    """
    Extract given strategy from param dict.

    Parameters
    ----------
    param : dict
        saving all parameters
    name : str
        strategy name

    Returns
    -------
    dict :
        with given strategy as value
    """
    param_new = copy.deepcopy(param)
    return {k: v[name] for k, v in six.iteritems(param_new)
            if k != 'non_fitting_values'}


def define_param_bound_type(param,
                            strategy_list=['adjust_element2, adjust_element3'],
                            b_type='fixed'):
    param_new = copy.deepcopy(param)
    for k, v in six.iteritems(param_new):
        for data in strategy_list:
            if data in v.keys():
                param_new[k][data] = b_type
    return param_new


def extract_result(data, element):
    """
    Extract fitting result returned from fitting of multi files.

    Parameters
    ----------
    data : list
        list of dict
    element : str
        elemental line
    """
    data_map = []
    for v in data:
        data_map.append(v[element])
    return np.array(data_map)


def bin_data_pixel(data, nearest_n=4):
    """
    Bin 3D data according to number of pixels defined in dim 1 and 2.

    Parameters
    ----------
    data : 3D array
        exp data with energy channel in 3rd dim.
    nearest_n : int, optional
        define how many pixels to be considered.
    """
    new_data = np.array(data)
    d_shape = data.shape

    # if nearest_n == 4:
    #     for i in [-1, 1]:
    #         new_data[1:-1, 1:-1, :] += data[1+i:d_shape[0]-1+i, 1:d_shape[1]-1, :]
    #     for j in [-1, 1]:
    #         new_data[1:-1, 1:-1, :] += data[1:d_shape[0]-1, 1+j:d_shape[1]-1+j, :]

    if nearest_n == 4:
        for i in np.arange(d_shape[0]-1):
            for j in np.arange(d_shape[1]-1):
                new_data[i, j, :] += (new_data[i+1, j, :] +
                                      new_data[i, j+1, :] +
                                      new_data[i+1, j+1, :])
        new_data[:-1, :-1, :] /= nearest_n

    if nearest_n == 9:
        for i in [-1, 0, 1]:
            for j in [-1, 0, 1]:
                new_data[1:-1, 1:-1, :] += data[1+i:d_shape[0]-1+i, 1+j:d_shape[1]-1+j, :]

        new_data[1:-1, 1:-1, :] /= nearest_n

    return new_data


def bin_data_spacial(data, bin_size=4):
    """
    Bin 2D/3D data based on first and second dim, i.e., 2 by 2 window, or 4 by 4.

    Parameters
    ----------
    data : array
        2D or 3D dataset
    bin_size : int
        window size. 2 means 2 by 2 window
    """
    if bin_size <= 1:
        return data

    data = np.asarray(data)
    if data.ndim == 2:
        d_shape = np.array([data.shape[0], data.shape[1]])/bin_size

        data_new = np.zeros([d_shape[0], d_shape[1]])
        for i in np.arange(d_shape[0]):
            for j in np.arange(d_shape[1]):
                data_new[i, j] = np.sum(data[i*bin_size:i*bin_size+bin_size,
                                             j*bin_size:j*bin_size+bin_size])
    elif data.ndim == 3:
        d_shape = np.array([data.shape[0], data.shape[1]])/bin_size

        data_new = np.zeros([d_shape[0], d_shape[1], data.shape[2]])
        for i in np.arange(d_shape[0]):
            for j in np.arange(d_shape[1]):
                data_new[i, j, :] = np.sum(data[i*bin_size:i*bin_size+bin_size,
                                                j*bin_size:j*bin_size+bin_size, :], axis=(0, 1))
    return data_new


def conv_expdata_energy(data, width=2):
    """
    Do convolution on the 3rd axis, energy axis.
    Paremeters
    ----------
    data : 3D array
        exp spectrum
    width : int, optional
        width of the convolution function.
    Returns
    -------
    array :
        after convolution
    """
    data_new = np.array(data)
    if width == 2:
        conv_f = [1.0/2, 1.0/2]
    if width == 3:
        conv_f = [1.0/3, 1.0/3, 1.0/3]
    for i in np.arange(data.shape[0]):
        for j in np.arange(data.shape[1]):
            data_new[i, j, :] = np.convolve(data_new[i, j, :], conv_f, mode='same')

    return data_new


def bin_data_energy2D(data, bin_step=2, axis_v=0, sum_data=False):
    """
    Bin data based on given dim, i.e., a dim for energy spectrum.
    Return a copy of the data. Currently only binning along first
    dim is implemented.

    Parameters
    ----------
    data : 2D array
    bin_step : int, optional
        size to bin the data
    axis_v : int, optional
        along which dir to bin data.
    sum_data : bool, optional
        sum data from each bin or not

    Returns
    -------
    binned data with reduced dim of the previous size.
    """
    if bin_step == 1:
        return data

    data = np.array(data)
    if axis_v == 0:
        if bin_step == 2:
            new_len = data.shape[0]/bin_step
            m1 = data[::2, :]
            m2 = data[1::2, :]
            if sum_data is True:
                return (m1[:new_len, :] +
                        m2[:new_len, :])/bin_step
            else:
                return m1[:new_len, :]
        elif bin_step == 3:
            new_len = data.shape[0]/bin_step
            m1 = data[::3, :]
            m2 = data[1::3, :]
            m3 = data[2::3, :]
            if sum_data is True:
                return (m1[:new_len, :] +
                        m2[:new_len, :] +
                        m3[:new_len, :])/bin_step
            else:
                return m1[:new_len, :]
        elif bin_step == 4:
            new_len = data.shape[0]/bin_step
            m1 = data[::4, :]
            m2 = data[1::4, :]
            m3 = data[2::4, :]
            m4 = data[3::4, :]
            if sum_data is True:
                return (m1[:new_len, :] +
                        m2[:new_len, :] +
                        m3[:new_len, :] +
                        m4[:new_len, :])/bin_step
            else:
                return m1[:new_len, :]


def bin_data_energy3D(data, bin_step=2, sum_data=False):
    """
    Bin 3D data along 3rd axis, i.e., a dim for energy spectrum.
    Return a copy of the data.

    Parameters
    ----------
    data : 3D array
    sum_data : bool, optional
        sum data from each bin or not

    Returns
    -------
    binned data with reduced dim of the previous size.
    """
    if bin_step == 1:
        return data
    data = np.array(data)
    if bin_step == 2:
        new_len = data.shape[2]/2
        new_data1 = data[:, :, ::2]
        new_data2 = data[:, :, 1::2]
        if sum_data == True:
            return (new_data1[:, :, :new_len] +
                    new_data2[:, :, :new_len])/bin_step
        else:
            return new_data1[:, :, :new_len]
    elif bin_step == 3:
        new_len = data.shape[2]/3
        new_data1 = data[:, :, ::3]
        new_data2 = data[:, :, 1::3]
        new_data3 = data[:, :, 2::3]
        if sum_data == True:
            return (new_data1[:, :, :new_len] +
                    new_data2[:, :, :new_len] +
                    new_data3[:, :, :new_len] )/bin_step
        else:
            return new_data1[:, :, :new_len]
    elif bin_step == 4:
        new_len = data.shape[2]/4
        new_data1 = data[:, :, ::4]
        new_data2 = data[:, :, 1::4]
        new_data3 = data[:, :, 2::4]
        new_data4 = data[:, :, 3::4]
        if sum_data == True:
            return (new_data1[:, :, :new_len] +
                    new_data2[:, :, :new_len] +
                    new_data3[:, :, :new_len] +
                    new_data4[:, :, :new_len])/bin_step
        else:
            return new_data1[:, :, :new_len]


def cal_r2(y, y_cal):
    """
    Calculate r2 statistics.
    Parameters
    ----------
    y : array
        exp data
    y_cal : array
        fitted data
    Returns
    -------
    float
    """
    sse = np.sum((y-y_cal)**2)
    sst = np.sum((y - np.mean(y))**2)
    return 1-sse/sst


def calculate_area(e_select, matv, results,
                   param, first_peak_area=False):
    """
    Parameters
    ----------
    e_select : list
        elements
    matv : 2D array
        matrix constains elemental profile as columns
    results : 3D array
        x, y positions, and each element's weight on third dim
    param : dict
        parameters of fitting
    first_peak_area : Bool, optional
        get overal peak area or only the first peak area, such as Ar_Ka1

    Returns
    -------
    dict :
        dict of each 2D elemental distribution
    """
    total_list = e_select + ['snip_bkg'] + ['r_squared']
    mat_sum = np.sum(matv, axis=0)

    result_map = dict()
    for i in range(len(e_select)):
        if first_peak_area is not True:
            result_map.update({total_list[i]: results[:, :, i]*mat_sum[i]})
        else:
            if total_list[i] not in K_LINE+L_LINE+M_LINE:
                ratio_v = 1
            else:
                ratio_v = get_branching_ratio(total_list[i],
                                              param['coherent_sct_energy']['value'])
            result_map.update({total_list[i]: results[:, :, i]*mat_sum[i]*ratio_v})

    # add background and res
    result_map.update({total_list[-2]: results[:, :, -2]})
    result_map.update({total_list[-1]: results[:, :, -1]})

    return result_map


def save_fitted_fig(x_v, matv, results,
                    p1, p2, data_all, param_dict,
                    result_folder, use_sinp=False):
    """
    Save single pixel fitting resutls to figs.
    """
    low_limit_v = 0.5

    fig, ax = plt.subplots(nrows=1, ncols=1)
    ax.set_xlabel('Energy [keV]')
    ax.set_ylabel('Counts')
    max_v = np.max(data_all[p1[0]:p2[0], p1[1]:p2[1], :])

    fitted_sum = None
    for m in range(p1[0], p2[0]):
        for n in range(p1[1], p2[1]):
            data_y = data_all[m, n, :]

            fitted_y = np.sum(matv*results[m, n, :], axis=1)
            if use_sinp is True:
                bg = snip_method(data_y,
                                 param_dict['e_offset']['value'],
                                 param_dict['e_linear']['value'],
                                 param_dict['e_quadratic']['value'],
                                 width=param_dict['non_fitting_values']['background_width'])
                fitted_y += bg

            if fitted_sum is None:
                fitted_sum = fitted_y
            else:
                fitted_sum += fitted_y
            ax.cla()
            ax.set_title('Single pixel fitting for point ({}, {})'.format(m, n))
            ax.set_xlabel('Energy [keV]')
            ax.set_ylabel('Counts')
            ax.set_ylim(low_limit_v, max_v*2)

            ax.semilogy(x_v, data_y, label='exp', linestyle='', marker='.')
            ax.semilogy(x_v, fitted_y, label='fit')

            ax.legend()
            output_path = os.path.join(result_folder,
                                       'data_out_'+str(m)+'_'+str(n)+'.png')
            plt.savefig(output_path)

    ax.cla()
    sum_y = np.sum(data_all[p1[0]:p2[0], p1[1]:p2[1], :], axis=(0, 1))
    ax.set_title('Summed spectrum from point ({},{}) '
                 'to ({},{})'.format(p1[0], p1[1], p2[0], p2[1]))
    ax.set_xlabel('Energy [keV]')
    ax.set_ylabel('Counts')
    ax.set_ylim(low_limit_v, np.max(sum_y)*2)
    ax.semilogy(x_v, sum_y, label='exp', linestyle='', marker='.')
    ax.semilogy(x_v, fitted_sum, label='fit', color='red')

    ax.legend()
    fit_sum_name = 'pixel_sum_'+str(p1[0])+'-'+str(p1[1])+'_'+str(p2[0])+'-'+str(p2[1])+'.png'
    output_path = os.path.join(result_folder, fit_sum_name)
    plt.savefig(output_path)


def save_fitted_as_movie(x_v, matv, results,
                         p1, p2, data_all, param_dict,
                         result_folder, prefix=None, use_sinp=False, dpi=150):
    """
    Create movie to save single pixel fitting resutls.
    """
    total_n = data_all.shape[1]*p2[0]

    fig, ax = plt.subplots(nrows=1, ncols=1)
    ax.set_aspect('equal')
    ax.set_xlabel('Energy [keV]')
    ax.set_ylabel('Counts')
    max_v = np.max(data_all[p1[0]:p2[0], p1[1]:p2[1], :])
    ax.set_ylim([0, 1.1*max_v])

    l1,  = ax.plot(x_v,  x_v, label='exp', linestyle='-', marker='.')
    l2,  = ax.plot(x_v,  x_v, label='fit', color='red', linewidth=2)

    fitted_sum = None
    plist = []
    for v in range(total_n):
        m = v / data_all.shape[1]
        n = v % data_all.shape[1]
        if m>=p1[0] and m<=p2[0] and n>=p1[1] and n<=p2[1]:
            plist.append((m,n))

    def update_img(p_val):
        m = p_val[0]
        n = p_val[1]
        data_y = data_all[m, n, :]

        fitted_y = np.sum(matv*results[m, n, :], axis=1)
        if use_sinp is True:
            bg = snip_method(data_y,
                             param_dict['e_offset']['value'],
                             param_dict['e_linear']['value'],
                             param_dict['e_quadratic']['value'],
                             width=param_dict['non_fitting_values']['background_width'])
            fitted_y += bg

        ax.set_title('Single pixel fitting for point ({}, {})'.format(m, n))
        #ax.set_ylim(low_limit_v, max_v*2)
        l1.set_ydata(data_y)
        l2.set_ydata(fitted_y)
        return l1, l2

    writer = animation.writers['ffmpeg'](fps=30)
    ani = animation.FuncAnimation(fig, update_img, plist)
    if prefix:
        output_file = prefix+'_pixel.mp4'
    else:
        output_file = 'fit_pixel.mp4'
    output_p = os.path.join(result_folder, output_file)
    ani.save(output_p, writer=writer, dpi=dpi)


def fit_per_line_nnls_wrapper(row_num, data, matv, param, use_snip):
    """Wraps fit_per_line_nnls in skbeam and logs which row is being computed

    Parameters
    ----------
    row_num : int
        which row to fit
    data : array
        selected one row of experiment spectrum
    matv : array
        matrix for regression analysis
    param : dict
        fitting parameters
    use_snip : bool
        use snip algorithm to remove background or not

    Returns
    -------
    array :
        fitting values for all the elements at a given row. Background is
        calculated as a summed value. Also residual is included.
    """
    logger.info('Row number at {}'.format(row_num))
    return fit_per_line_nnls(data, matv, param, use_snip)


def fit_pixel_multiprocess_nnls(exp_data, matv, param, use_snip=False):
    """
    Multiprocess fit of experiment data.

    Parameters
    ----------
    exp_data : array
        3D data of experiment spectrum
    matv : array
        matrix for regression analysis
    param : dict
        fitting parameters
    use_snip : bool, optional
        use snip algorithm to remove background or not

    Returns
    -------
    dict :
        fitting values for all the elements
    """
    num_processors_to_use = multiprocessing.cpu_count()

    logger.info('cpu count: {}'.format(num_processors_to_use))
    pool = multiprocessing.Pool(num_processors_to_use)

    result_pool = [pool.apply_async(fit_per_line_nnls,
                                    (n, exp_data[n, :, :], matv,
                                     param, use_snip))
                   for n in range(exp_data.shape[0])]

    results = []
    for r in result_pool:
        results.append(r.get())

    pool.terminate()
    pool.join()

    results = np.array(results)

    return results


# def simple_spectrum_fun_for_nonlinear(x, **kwargs):
#     return np.sum(kwargs['a{}'.format(i)] * reg_mat[:, i] for i in range(len(kwargs)))


def spectrum_nonlinear_fit(pars, x, reg_mat):
    vals = pars.valuesdict()
    return np.sum(vals['a{}'.format(i)] * reg_mat[:, i] for i in range(len(vals)))


def residual_nonlinear_fit(pars, x, data=None, reg_mat=None):
    return spectrum_nonlinear_fit(pars, x, reg_mat) - data


def fit_pixel_nonlinear_per_line(row_num, data, x0,
                                 param, reg_mat,
                                 use_snip):
                                 #c_weight, fit_num, ftol):

    c_weight = 1
    fit_num = 100
    ftol = 1e-3

    elist = param['non_fitting_values']['element_list'].split(', ')
    elist = [e.strip(' ') for e in elist]

    # LinearModel = lmfit.Model(simple_spectrum_fun_for_nonlinear)
    # for i in np.arange(reg_mat.shape[0]):
    #     LinearModel.set_param_hint('a'+str(i), value=0.1, min=0, vary=True)

    logger.info('Row number at {}'.format(row_num))
    out = []
    snip_bg = 0
    for i in range(data.shape[0]):
        if use_snip is True:
            bg = snip_method(data[i, :],
                             param['e_offset']['value'],
                             param['e_linear']['value'],
                             param['e_quadratic']['value'],
                             width=param['non_fitting_values']['background_width'])
            y0 = data[i, :] - bg
            snip_bg = np.sum(bg)
        else:
            y0 = data[i, :]

        fit_params = lmfit.Parameters()
        for i in range(reg_mat.shape[1]):
            fit_params.add('a'+str(i), value=1.0, min=0, vary=True)

        result = lmfit.minimize(residual_nonlinear_fit,
                                fit_params, args=(x0,),
                                kws={'data':y0, 'reg_mat':reg_mat})
        # result = MS.model_fit(x0, y0,
        #                       weights=1/np.sqrt(c_weight+y0),
        #                       maxfev=fit_num,
        #                       xtol=ftol, ftol=ftol, gtol=ftol)
        #namelist = result.keys()
        temp = {}
        temp['value'] = [result.params[v].value for v in result.params.keys()]
        temp['err'] = [result.params[v].stderr for v in result.params.keys()]
        temp['snip_bg'] = snip_bg
        out.append(temp)
    return out


def fit_pixel_multiprocess_nonlinear(data, x, param, reg_mat, use_snip=False):
    """
    Multiprocess fit of experiment data.

    Parameters
    ----------
    data : array
        3D data of experiment spectrum
    param : dict
        fitting parameters

    Returns
    -------
    dict :
        fitting values for all the elements
    """

    num_processors_to_use = multiprocessing.cpu_count()
    logger.info('cpu count: {}'.format(num_processors_to_use))
    pool = multiprocessing.Pool(num_processors_to_use)

    # fit_params = lmfit.Parameters()
    # for i in range(reg_mat.shape[1]):
    #     fit_params.add('a'+str(i), value=1.0, min=0, vary=True)

    result_pool = [pool.apply_async(fit_pixel_nonlinear_per_line,
                                    (n, data[n, :, :], x,
                                     param, reg_mat, use_snip))
                   for n in range(data.shape[0])]

    results = []
    for r in result_pool:
        results.append(r.get())

    pool.terminate()
    pool.join()

    return results


def get_area_and_error_nonlinear_fit(elist, fit_results, reg_mat):

    mat_sum = np.sum(reg_mat, axis=0)
    area_dict = OrderedDict()
    error_dict = OrderedDict()
    for name in elist:
        area_dict[name] = np.zeros([len(fit_results), len(fit_results[0])])
        error_dict[name] = np.zeros([len(fit_results), len(fit_results[0])])
    #area_dict = OrderedDict({name:np.zeros([len(fit_results), len(fit_results[0])]) for name in elist})
    #error_dict = OrderedDict({name:np.zeros([len(fit_results), len(fit_results[0])]) for name in elist})
    area_dict['snip_bg'] = np.zeros([len(fit_results), len(fit_results[0])])
    weights_mat = np.zeros([len(fit_results), len(fit_results[0]), len(error_dict)])

    for i in range(len(fit_results)):
        for j in range(len(fit_results[0])):
            for m, v in enumerate(six.iterkeys(area_dict)):
                if v=='snip_bg':
                    area_dict[v][i, j] = fit_results[i][j]['snip_bg']
                else:
                    area_dict[v][i, j] = fit_results[i][j]['value'][m]
                    error_dict[v][i, j] = fit_results[i][j]['err'][m]
                    weights_mat[i,j,m] = fit_results[i][j]['value'][m]

    for i,v in enumerate(six.iterkeys(area_dict)):
        if v=='snip_bg':
            continue
        area_dict[v] *= mat_sum[i]
        error_dict[v] *= mat_sum[i]

    return area_dict, error_dict, weights_mat


def single_pixel_fitting_controller(input_data, param, method='nnls',
                                    pixel_bin=0, raise_bg=0,
                                    comp_elastic_combine=False,
                                    linear_bg=False,
                                    use_snip=True,
                                    bin_energy=1):
    """
    Parameters
    ----------
    input_data : array
        3D array of spectrum
    param : dict
        parameter for fitting
    method : str, optional
        fitting method, default as nnls
    pixel_bin : int, optional
        bin pixel as 2by2, or 3by3
    raise_bg : int, optional
        add a constant value to each spectrum, better for fitting
    comp_elastic_combine : bool, optional
        combine elastic and compton as one component for fitting
    linear_bg : bool, optional
        use linear background instead of snip
    use_snip : bool, optional
        use snip method to remove background
    bin_energy : int, optional
        bin spectrum with given value

    Returns
    -------
    result_map : dict
        of elemental map for given elements
    calculation_info : dict
        dict of fitting information
    """
    # cut data into proper range
    x, exp_data, fit_range = get_cutted_spectrum_in3D(input_data,
                                                      param['non_fitting_values']['energy_bound_low']['value'],
                                                      param['non_fitting_values']['energy_bound_high']['value'],
                                                      param['e_offset']['value'],
                                                      param['e_linear']['value'])

    # calculate matrix for regression analysis
    elist = param['non_fitting_values']['element_list'].split(', ')
    elist = [e.strip(' ') for e in elist]
    e_select, matv, e_area = construct_linear_model(x, param, elist)

    if comp_elastic_combine is True:
        e_select = e_select[:-1]
        e_select[-1] = 'comp_elastic'

        matv_old = np.array(matv)
        matv = matv_old[:, :-1]
        matv[:, -1] += matv_old[:, -1]

    if linear_bg is True:
        e_select.append('const_bkg')

        matv_old = np.array(matv)
        matv = np.ones([matv_old.shape[0], matv_old.shape[1]+1])
        matv[:, :-1] = matv_old

    logger.info('Matrix used for linear fitting has components: {}'.format(e_select))

    # add const background, so nnls works better for values above zero
    if raise_bg > 0:
        exp_data += raise_bg

    # bin data based on nearest pixels, only two options
    if pixel_bin in [4, 9]:
        logger.info('Bin pixel data with parameter: {}'.format(pixel_bin))
        exp_data = bin_data_spacial(exp_data, bin_size=int(np.sqrt(pixel_bin)))
        # exp_data = bin_data_pixel(exp_data, nearest_n=pixel_bin)  # return a copy of data

    # bin data based on energy spectrum
    if bin_energy in [2, 3]:
        exp_data = conv_expdata_energy(exp_data, width=bin_energy)

    # make matrix smaller for single pixel fitting
    matv /= exp_data.shape[0]*exp_data.shape[1]

    error_map = None

    if method == 'nnls':
        logger.info('Fitting method: non-negative least squares')
        results = fit_pixel_multiprocess_nnls(exp_data, matv, param,
                                              use_snip=use_snip)
        # output area of dict
        result_map = calculate_area(e_select, matv, results,
                                    param, first_peak_area=False)
    else:
        logger.info('Fitting method: nonlinear least squares')
        matrix_norm = exp_data.shape[0]*exp_data.shape[1]
        fit_results = fit_pixel_multiprocess_nonlinear(exp_data, x, param, matv/matrix_norm,
                                                       use_snip=use_snip)

        result_map, error_map, results = get_area_and_error_nonlinear_fit(e_select,
                                                                          fit_results,
                                                                          matv/matrix_norm)

    calculation_info = dict()
    if error_map is not None:
        calculation_info['error_map'] = error_map

    calculation_info['fit_name'] = e_select
    calculation_info['regression_mat'] = matv
    calculation_info['results'] = results
    calculation_info['fit_range'] = fit_range
    calculation_info['energy_axis'] = x
    calculation_info['exp_data'] = exp_data

    return result_map, calculation_info


def get_cutted_spectrum_in3D(exp_data, low_e, high_e,
                             e_offset, e_linear):
    """
    Cut exp data on the 3rd axis, energy axis.
    Parameters
    ----------
    exp_data : 3D array
    low_e : float
        low energy bound in KeV
    high_e : float
        high energy bound in KeV
    e_offset : float
        offset term in energy calibration
    e_linear : float
        linear term in energy calibration
    Returns
    -------
    x : array
        channel data
    data : 3D array
        after cutting into the correct range
    list :
        fitting range
    """

    # cut range
    data = np.array(exp_data)
    y0 = data[0, 0, :]
    x0 = np.arange(len(y0))

    # transfer energy value back to channel value
    lowv = (low_e - e_offset) / e_linear
    highv = (high_e - e_offset) / e_linear
    lowv = int(lowv)
    highv = int(highv)
    x, y = trim(x0, y0, lowv, highv)

    data = data[:, :, lowv: highv+1]
    return x, data, [lowv, highv]


def get_branching_ratio(elemental_line, energy):
    """
    Calculate the ratio of branching ratio, such as ratio of
    branching ratio of Ka1 to sum of br of all K lines.

    Parameters
    ----------
    elemental_line : str
        e.g., 'Mg_K', refers to the K lines of Magnesium
    energy : float
        incident energy in keV

    Returns
    -------
    float :
        calculated ratio
    """

    name, line = elemental_line.split('_')
    e = Element(name)
    transition_lines = TRANSITIONS_LOOKUP[line.upper()]

    sum_v = 0
    for v in transition_lines:
        sum_v += e.cs(energy)[v]
    ratio_v = e.cs(energy)[transition_lines[0]]/sum_v
    return ratio_v


def fit_pixel_data_and_save(working_directory, file_name,
                            fit_channel_sum=True, param_file_name=None,
                            fit_channel_each=False, param_channel_list=[],
                            incident_energy=None,
                            method='nnls', pixel_bin=0, raise_bg=0,
                            comp_elastic_combine=False,
                            linear_bg=False,
                            use_snip=True,
                            bin_energy=0,
                            spectrum_cut=3000,
                            save_txt=False,
                            save_tiff=True):
    """
    Do fitting for multiple data sets, and save data accordingly. Fitting can be performed on
    either summed data or each channel data, or both.

    Parameters
    ----------
    working_directory : str
        path folder
    file_names : str
        selected h5 file
    fit_channel_sum : bool, optional
        fit summed data or not
    param_file_name : str, optional
        param file name for summed data fitting
    fit_channel_each : bool, optional
        fit each channel data or not
    param_channel_list : list, optional
        list of param file names for each channel
    incident_energy : float, optional
        use this energy as incident energy instead of the one in param file, i.e., XANES
    method : str, optional
        fitting method, default as nnls
    pixel_bin : int, optional
        bin pixel as 2by2, or 3by3
    raise_bg : int, optional
        add a constant value to each spectrum, better for fitting
    comp_elastic_combine : bool, optional
        combine elastic and compton as one component for fitting
    linear_bg : bool, optional
        use linear background instead of snip
    use_snip : bool, optional
        use snip method to remove background
    bin_energy : int, optional
        bin spectrum with given value
    spectrum_cut : int, optional
        only use spectrum from, say 0, 3000
    save_txt : bool, optional
        save data to txt or not
    save_tiff : bool, optional
        save data to tiff or not
    """
    fpath = os.path.join(working_directory, file_name)
    t0 = time.time()
    prefix_fname = file_name.split('.')[0]
    if fit_channel_sum is True:
        img_dict, data_sets = read_hdf_APS(working_directory, file_name,
                                           spectrum_cut=spectrum_cut,
                                           load_each_channel=False)

        data_all_sum = data_sets[prefix_fname+'_sum'].raw_data
        # load param file
        param_path = os.path.join(working_directory, param_file_name)
        with open(param_path, 'r') as json_data:
            param_sum = json.load(json_data)

        # update incident energy, required for XANES
        if incident_energy is not None:
            param_sum['coherent_sct_amplitude']['value'] = incident_energy

        result_map_sum, calculation_info = single_pixel_fitting_controller(data_all_sum,
                                                                           param_sum,
                                                                           method=method,
                                                                           pixel_bin=pixel_bin,
                                                                           raise_bg=raise_bg,
                                                                           comp_elastic_combine=comp_elastic_combine,
                                                                           linear_bg=linear_bg,
                                                                           use_snip=use_snip,
                                                                           bin_energy=bin_energy)

        # output to .h5 file
        inner_path = 'xrfmap/detsum'
        fit_name = prefix_fname+'_fit'
        save_fitdata_to_hdf(fpath, result_map_sum, datapath=inner_path)

    if fit_channel_each is True:
        channel_num = len(param_channel_list)
        img_dict, data_sets = read_hdf_APS(working_directory, file_name,
                                           channel_num=channel_num,
                                           spectrum_cut=spectrum_cut,
                                           load_each_channel=True)
        for i in range(channel_num):
            filename_det = prefix_fname+'_ch'+str(i+1)
            inner_path = 'xrfmap/det'+str(i+1)

            # load param file
            param_file_det = param_channel_list[i]
            param_path = os.path.join(working_directory, param_file_det)
            with open(param_path, 'r') as json_data:
                param_det = json.load(json_data)

            # update incident energy, required for XANES
            if incident_energy is not None:
                param_det['coherent_sct_amplitude']['value'] = incident_energy

            data_all_det = data_sets[filename_det].raw_data
            result_map_det, calculation_info = single_pixel_fitting_controller(data_all_det,
                                                                               param_det,
                                                                               method=method,
                                                                               pixel_bin=pixel_bin,
                                                                               raise_bg=raise_bg,
                                                                               comp_elastic_combine=comp_elastic_combine,
                                                                               linear_bg=linear_bg,
                                                                               use_snip=use_snip,
                                                                               bin_energy=bin_energy)
            # output to .h5 file
            save_fitdata_to_hdf(fpath, result_map_det, datapath=inner_path)

    t1 = time.time()
    print('Time used for pixel fitting for file {} is : {}'.format(file_name, t1-t0))

    if save_txt is True:
        output_folder = 'output_txt_'+prefix_fname
        output_data(fpath, output_folder, file_format='txt')
    if save_tiff is True:
        output_folder = 'output_tiff_'+prefix_fname
        output_data(fpath, output_folder, file_format='tiff')


def save_fitdata_to_hdf(fpath, data_dict,
                        datapath='xrfmap/detsum',
                        data_saveas='xrf_fit',
                        dataname_saveas='xrf_fit_name'):
    """
    Add fitting results to existing h5 file. This is to be moved to filestore.

    Parameters
    ----------
    fpath : str
        path of the hdf5 file
    data_dict : dict
        dict of array
    datapath : str
        path inside h5py file
    data_saveas : str, optional
        name in hdf for data array
    dataname_saveas : str, optional
        name list in hdf to explain what the saved data mean
    """
    f = h5py.File(fpath, 'a')
    try:
        dataGrp = f.create_group(datapath)
    except ValueError:
        dataGrp=f[datapath]

    data = []
    namelist = []
    for k, v in six.iteritems(data_dict):
        namelist.append(str(k))
        data.append(v)

    if data_saveas in dataGrp:
        del dataGrp[data_saveas]

    data = np.array(data)
    ds_data = dataGrp.create_dataset(data_saveas, data=data)
    ds_data.attrs['comments'] = ' '

    if dataname_saveas in dataGrp:
        del dataGrp[dataname_saveas]

    name_data = dataGrp.create_dataset(dataname_saveas, data=namelist)
    name_data.attrs['comments'] = ' '

    f.close()


def ccombine_data_to_hdf(fpath_read, file_prefix,
                         start_id, end_id,
                         interpath_read='entry/instrument/detector/data'):
    """
    Read data from each point scan, then save them to one hdf file.
    Following APS X13 beamline structure.
    """
    datasum = None
    for i in range(start_id, end_id+1):
        num_str = '{:03d}'.format(i)
        filename = file_prefix + num_str
        file_path = os.path.join(fpath_read, filename)
        with h5py.File(file_path, 'r') as f:
            data_temp = f[interpath_read][:]
            #data_temp = np.asarray(data_temp)
            #datasum.append(np.sum(data_temp, axis=1))
            if datasum is None:
                datasum = np.zeros([end_id-start_id+1,
                                    data_temp.shape[0],
                                    data_temp.shape[1],
                                    data_temp.shape[2]])
            datasum[i-start_id, :, :, :] = data_temp

    return datasum


def fit_pixel_fast(dir_path, file_prefix,
                   fileID, param, interpath,
                   save_spectrum=True):
    """
    Single pixel fit of experiment data. No multiprocess is applied.

    .. warning :: This function is not optimized as it calls
    linear_spectrum_fitting function, where lots of repeated
    calculation are processed.

    Parameters
    ----------
    data : array
        3D data of experiment spectrum
    param : dict
        fitting parameters

    Returns
    -------
    dict :
        fitting values for all the elements
    """

    num_str = '{:03d}'.format(fileID)
    filename = file_prefix + num_str
    file_path = os.path.join(dir_path, filename)
    with h5py.File(file_path, 'r') as f:
        data = f[interpath][:]
    datas = data.shape

    elist = param['non_fitting_values']['element_list'].split(', ')
    elist = [e.strip(' ') for e in elist]

    non_element = ['compton', 'elastic', 'background']
    total_list = elist + non_element

    result_map = dict()
    for v in total_list:
        if save_spectrum:
            result_map.update({v: np.zeros([datas[0], datas[1], datas[2]])})
        else:
            result_map.update({v: np.zeros([datas[0], datas[1]])})

    for i in xrange(datas[0]):
        for j in xrange(datas[1]):
            x, result, area_v = linear_spectrum_fitting(data[i, j, :], param,
                                                        elemental_lines=elist,
                                                        constant_weight=1.0)
            for v in total_list:
                if v in result:
                    if save_spectrum:
                        result_map[v][i, j, :len(result[v])] = result[v]
                    else:
                        result_map[v][i, j] = np.sum(result[v])

    return result_map


def fit_data_multi_files(dir_path, file_prefix,
                         param, start_i, end_i,
                         interpath='entry/instrument/detector/data'):
    """
    Fitting for multiple files with Multiprocessing.

    Parameters
    ----------
    dir_path : str
    file_prefix : str
    param : dict
    start_i : int
        start id of given file
    end_i: int
        end id of given file
    interpath : str
        path inside hdf5 file to fetch the data

    Returns
    -------
    result : list
        fitting result as list of dict
    """
    num_processors_to_use = multiprocessing.cpu_count()
    logger.info('cpu count: {}'.format(num_processors_to_use))
    #print 'Creating pool with %d processes\n' % num_processors_to_use
    pool = multiprocessing.Pool(num_processors_to_use)

    result_pool = [pool.apply_async(fit_pixel_fast,
                                    (dir_path, file_prefix,
                                     m, param, interpath))
                   for m in range(start_i, end_i+1)]

    results = []
    for r in result_pool:
        results.append(r.get())

    pool.terminate()
    pool.join()
    return results


def roi_sum_calculation(dir_path, file_prefix, fileID,
                        element_dict, interpath):
    """
    Parameters
    -----------
    dir_path : str
    file_prefix : str
    fileID : int
    element_dict : dict
        element name with low/high bound
    interpath : str
        path inside hdf5 file to fetch the data

    Returns
    -------
    result : dict
        roi sum for all given elements
    """
    num_str = '{:03d}'.format(fileID)
    #logger.info('File number is {}'.format(fileID))
    filename = file_prefix + num_str
    file_path = os.path.join(dir_path, filename)
    with h5py.File(file_path, 'r') as f:
        data = f[interpath][:]

    result_map = dict()
    #for v in six.iterkeys(element_dict):
    #    result_map[v] = np.zeros([datas[0], datas[1]])

    for k, v in six.iteritems(element_dict):
        result_map[k] = np.sum(data[:, :, v[0]: v[1]], axis=2)

    return result_map


def roi_sum_multi_files(dir_path, file_prefix,
                        start_i, end_i, element_dict,
                        interpath='entry/instrument/detector/data'):
    """
    Fitting for multiple files with Multiprocessing.

    Parameters
    -----------
    dir_path : str
    file_prefix : str
    start_i : int
        start id of given file
    end_i: int
        end id of given file
    element_dict : dict
        dict of element with [low, high] bounds as values
    interpath : str
        path inside hdf5 file to fetch the data

    Returns
    -------
    result : list
        fitting result as list of dict
    """
    num_processors_to_use = multiprocessing.cpu_count()
    logger.info('cpu count: {}'.format(num_processors_to_use))
    pool = multiprocessing.Pool(num_processors_to_use)

    result_pool = [pool.apply_async(roi_sum_calculation,
                                    (dir_path, file_prefix,
                                     m, element_dict, interpath))
                   for m in range(start_i, end_i+1)]

    results = []
    for r in result_pool:
        results.append(r.get())

    pool.terminate()
    pool.join()
    return results


def get_cs(elemental_line, eng=12, norm=False, round_n=2):
    """
    Calculate cross section in cm2/g.
    Parameters
    ----------
    elemental_line: str
        like Pt_L, Si_K
    eng : float
        incident energy in KeV
    norm : bool, optional
        normalized to the primary cs value or not.
    round_n : int
        number of decimal point.
    """
    if 'pileup' in elemental_line:
        return '-'
    elif '_K' in elemental_line:
        name_label = 'ka1'
        ename = elemental_line.split('_')[0]
    elif '_L' in elemental_line:
        name_label = 'la1'
        ename = elemental_line.split('_')[0]
    elif '_M' in elemental_line:
        name_label = 'ma1'
        ename = elemental_line.split('_')[0]
    else:
        return '-'

    e = Element(ename)
    sumv = 0
    for line_name in e.cs(eng).keys():
        if name_label[0] in line_name:
            sumv += e.cs(eng)[line_name]
    if norm is True:
        return np.around(sumv/e.cs(eng)[name_label], round_n)
    else:
        return np.around(sumv, round_n)


def fly2d_grid(dimv, rangex, rangey, start_x, start_y,
               x_data=None, y_data=None):
    '''Get ideal gridded points for a 2D flyscan'''
    # try:
    #     nx, ny = hdr['dimensions']
    # except ValueError:
    #     raise ValueError('Not a 2D flyscan (dimensions={})'
    #                      ''.format(hdr['dimensions']))
    nx, ny = dimv
    #rangex, rangey = hdr['scan_range']
    width = rangex[-1] - rangex[0]
    height = rangey[-1] - rangey[0]

    #macros = eval(hdr['subscan_0']['macros'], dict(array=np.array))
    #start_x, start_y = macros['scan_starts']
    dx = width / nx
    dy = height / ny
    grid_x = np.linspace(start_x, start_x + width + dx / 2, nx)
    grid_y = np.linspace(start_y, start_y + height + dy / 2, ny)

    return grid_x, grid_y


def interp1d_scan(dimv, rangex, rangey, start_x, start_y,
                  x_data, y_data, spectrum, kind='linear',
                  **kwargs):
    '''Interpolate a 2D flyscan only over the fast-scanning direction'''
    #grid_x, grid_y = fly2d_grid(hdr, x_data, y_data, plot=plot_points)
    grid_x, grid_y = fly2d_grid(dimv, rangex, rangey, start_x, start_y, x_data, y_data)
    #x_data = fly2d_reshape(hdr, x_data, verbose=False)
    #grid_x = flip_data(grid_x)

    if False:
        mesh_x, mesh_y = np.meshgrid(grid_x, grid_y)
        plt.figure()
        if x_data is not None and y_data is not None:
            plt.scatter(x_data, y_data, c='blue', label='actual')
        plt.scatter(mesh_x, mesh_y, c='red', label='gridded',
                    alpha=0.5)
        plt.legend()
        plt.show()

    spectrum2 = np.zeros_like(spectrum)
    for row in range(len(grid_y)):
        spectrum2[row, :] = interp1d(x_data[row, :], spectrum[row, :],
                                     kind=kind, bounds_error=False,
                                     **kwargs)(grid_x)

    return spectrum2


def interp2d_scan(dimv, rangex, rangey, start_x, start_y,
                  x_data, y_data, spectrum, kind='linear',
                  **kwargs):
    '''Interpolate a 2D flyscan over a grid, borrowed from Ken'''

    new_x, new_y = fly2d_grid(dimv, rangex, rangey, start_x, start_y, x_data, y_data)

    f = interp2d(x_data, y_data, spectrum, kind=kind, **kwargs)
    return f(new_x, new_y)
