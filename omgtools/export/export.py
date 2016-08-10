# This file is part of OMG-tools.
#
# OMG-tools -- Optimal Motion Generation-tools
# Copyright (C) 2016 Ruben Van Parys & Tim Mercy, KU Leuven.
# All rights reserved.
#
# OMG-tools is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 3 of the License, or (at your option) any later version.
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import os
import shutil


class Export(object):

    def __init__(self, problem, options):
        self.set_default_options()
        self.set_options(options)

    def set_default_options(self):
        self.options = {}
        self.options['directory'] = os.path.join(os.getcwd(), 'export/')
        self.options['casadi_optiflags'] = ''  # '', '-O3', '-Os'
        self.options['casadilib'] = '/usr/local/lib/'
        self.options['casadiinc'] = '/usr/local/include/casadi/'
        self.options['casadiobj'] = '.'
        self.options['sourcefiles'] = 'test.cpp Holonomic.cpp'
        self.options['executable'] = 'Executable'

    def set_options(self, options):
        self.options.update(options)
        if not os.path.isdir(self.options['directory']):
            os.makedirs(self.options['directory'])

    def export(self, source_dirs, export_dir, father, problem, point2point=None):
        if point2point is None:
            point2point = problem
        print 'Exporting ...',
        # copy files
        files = self.copy_files(source_dirs, export_dir)
        # export casadi problem(s)
        probsrc = self.export_casadi_problems(export_dir, father, problem)
        # create data to fill in in c++ template
        data = {}
        data.update(self.get_make_options(probsrc))
        data.update(self.create_defines(father, problem, point2point))
        data.update(self.create_types())
        data.update(self.create_functions(father, problem, point2point))
        # write data to template files
        self.fill_template(data, files.values())
        print 'done.'
        print 'Check out instructions.txt for build and usage instructions.'

    def copy_files(self, source_dirs, export_dir):
        this_path = os.path.dirname(os.path.realpath(__file__))
        files = {}
        no_src = ['Makefile', 'instructions.txt']
        for directory in source_dirs:
            dir_path = os.path.join(this_path, directory)
            sourcedir_files = os.listdir(dir_path)
            for f in sourcedir_files:
                if f in no_src:
                    files[os.path.join(dir_path, f)] = os.path.join(export_dir, f)
                else:
                    files[os.path.join(dir_path, f)] = os.path.join(export_dir, 'src/', f)
        for src, des in files.items():
            des_dir = os.path.dirname(des)
            if not os.path.isdir(des_dir):
                os.makedirs(des_dir)
            shutil.copy(src, des)
        return files

    def fill_template(self, data, files):
        if not isinstance(files, list):
            files = [files]
        for fil in files:
            with open(fil, 'r+') as f:
                if f is not None:
                    body = f.read()
                    for key, item in data.items():
                        body = body.replace('@'+key+'@', str(item))
                    f.seek(0)
                    f.truncate()
                    f.write(body)
                else:
                    raise ValueError('File '+os.path.join(self.src_dir, fil) +
                                     ' does not exist!')

    def export_casadi_problems(self, destination, father, problem):
        cwd = os.getcwd()
        filenames = []
        # substitutes
        for child, subst in father.substitutes.items():
            for name, fun in subst.items():
                filenames.append('subst_'+name+'.c')
                fun.generate(filenames[-1])
                shutil.move(cwd+'/'+filenames[-1], destination+'src/'+filenames[-1])
        return filenames

    def get_make_options(self, probsrc):
        make_opt = {'probsources': ' '.join(probsrc)}
        for key, option in self.options.items():
            make_opt[key] = option
        return make_opt

    def create_defines(self, father, problem, point2point):
        # create defines
        defines = {}
        defines['N_VAR'] = father._var_struct.size
        defines['N_PAR'] = father._par_struct.size
        defines['N_CON'] = father._con_struct.size
        defines['TOL'] = problem.options['solver_options']['ipopt']['ipopt.tol']
        defines['LINEAR_SOLVER'] = '"' + \
            problem.options['solver_options']['ipopt']['ipopt.linear_solver']+'"'
        defines['N_DIM'] = problem.vehicles[0].n_dim
        defines['N_OBS'] = problem.environment.n_obs
        defines['VEHICLELBL'] = '"' + problem.vehicles[0].label + '"'
        defines['P2PLBL'] = '"' + point2point.label + '"'
        defines['OBSTACLELBLS'] = '{' + ','.join(['"' + o.label + '"'
            for o in problem.environment.obstacles]) + '}'
        if point2point.__class__.__name__ == 'FreeTPoint2point':
            defines['FREET'] = 'true'
        elif point2point.__class__.__name__ == 'FixedTPoint2point':
            defines['FREET'] = 'false'
        else:
            raise ValueError('This type of point2point problem is not ' +
                             'supported for export')
        defines.update(self._create_spline_tf(father, problem))
        defines.update(self._create_lb_ub(father, problem))
        code = ''
        for name, define in defines.items():
            code += '#define ' + str(name) + ' ' + str(define) + '\n'
        return {'defines': code}

    def _create_spline_tf(self, father, problem):
        defines = {}
        for child in father.children.values():
            for name, spl in child._splines_prim.items():
                if name in child._variables:
                    if spl['init'] is not None:
                        tf = '{'
                        for k in range(spl['init'].shape[0]):
                            tf += '{'+','.join([str(t)
                                                for t in spl['init'][k].tolist()])+'},'
                        tf = tf[:-1]+'}'
                        defines.update({('%s_TF') % name.upper(): tf})
        return defines

    def _create_lb_ub(self, father, problem):
        defines = {}
        lb, ub, cnt = '{', '{', 0
        for child in father.children.values():
            for name, con in child._constraints.items():
                if con[0].size(1) > 1:
                    for l in range(con[0].size(1)):
                        lb += str(con[1][l])+','
                        ub += str(con[2][l])+','
                else:
                    lb += str(con[1])+','
                    ub += str(con[2])+','
                cnt += con[0].size(1)
        lb = lb[:-1]+'}'
        ub = ub[:-1]+'}'
        defines.update({'LBG_DEF': lb, 'UBG_DEF': ub})
        return defines

    def create_types(self):
        return {}

    def create_functions(self, father, problem, point2point):
        code = {}
        code.update(self._create_generateSubstituteFunctions(father))
        code.update(self._create_getParameterVector(father))
        code.update(self._create_getVariableVector(father))
        code.update(self._create_getVariableDict(father))
        code.update(self._create_updateBounds(father))
        code.update(self._create_initSplines(father, problem))
        code.update(self._create_transformSplines(father, problem, point2point))
        return code

    def _create_generateSubstituteFunctions(self, father):
        code = '\tstring obj_path = CASADIOBJ;\n'
        for child, subst in father.substitutes.items():
            for name, fun in subst.items():
                filename = 'subst_'+name+'.so'
                code += '\tsubstitutes["'+name+'"] = external("'+name+'", obj_path+"/'+filename+'");\n'
        return {'generateSubstituteFunctions': code}

    def _create_getParameterVector(self, father):
        code, cnt = '', 0
        for label, child in father.children.items():
            for name, par in child._parameters.items():
                if par.size(1) > 1:
                    code += '\tfor (int i=0; i<'+str(par.size(1)*par.size(2))+'; i++){\n'
                    code += ('\t\tpar_vect['+str(cnt) +
                             '+i] = par_dict["'+label+'"]["'+name+'"][i];\n')
                    code += '\t}\n'
                else:
                    code += '\tpar_vect['+str(cnt) + \
                        '] = par_dict["'+label+'"]["'+name+'"][0];\n'
                cnt += par.size(1)*par.size(2)
        return {'getParameterVector': code}

    def _create_getVariableVector(self, father):
        code, cnt = '', 0
        for label, child in father.children.items():
            code += '\tif (var_dict.find("'+label+'") != var_dict.end()){\n'
            for name, var in child._variables.items():
                code += '\t\tif (var_dict["'+label+'"].find("' + \
                    name+'") != var_dict["'+label+'"].end()){\n'
                if var.size(1) > 1:
                    code += '\t\t\tfor (int i=0; i<' + \
                        str(var.size(1)*var.size(2))+'; i++){\n'
                    code += ('\t\t\t\tvar_vect['+str(cnt) +
                             '+i] = var_dict["'+label+'"]["'+name+'"][i];\n')
                    code += '\t\t\t}\n'
                else:
                    code += '\t\t\tvar_vect[' + \
                        str(cnt)+'] = var_dict["'+label+'"]["'+name+'"][0];\n'
                code += '\t\t}\n'
                cnt += var.size(1)*var.size(2)
            code += '\t}\n'
        return {'getVariableVector': code}

    def _create_getVariableDict(self, father):
        code, cnt = '', 0
        code += '\tvector<double> vec;'
        for label, child in father.children.items():
            for name, var in child._variables.items():
                if var.size(1) > 1:
                    code += '\tvec.resize('+str(var.size(1)*var.size(2))+');\n'
                    code += '\tfor (int i=0; i<'+str(var.size(1)*var.size(2))+'; i++){\n'
                    code += '\t\tvec[i] = var_vect['+str(cnt)+'+i];\n'
                    code += '\t}\n'
                    code += '\tvar_dict["'+label+'"]["'+name+'"] = vec;\n'
                else:
                    code += '\tvar_dict["'+label+'"]["' + \
                        name+'"] = var_vect['+str(cnt)+'];\n'
                cnt += var.size(1)*var.size(2)
        return {'getVariableDict': code}

    def _create_updateBounds(self, father):
        code, cnt = '', 0
        _lbg, _ubg = father._lb.cat, father._ub.cat
        for child in father.children.values():
            for name, con in child._constraints.items():
                if child._add_label(name) in father._constraint_shutdown:
                    shutdown = father._constraint_shutdown[
                        child._add_label(name)]
                    cond = shutdown.replace('t', 'current_time')
                    code += '\tif(' + cond + '){\n'
                    for i in range(con[0].size(1)):
                        code += '\t\tlbg['+str(cnt+i)+'] = -INF;\n'
                        code += '\t\tubg['+str(cnt+i)+'] = +INF;\n'
                    code += '\t}else{\n'
                    for i in range(con[0].size(1)):
                        code += ('\t\tlbg['+str(cnt+i)+'] = ' +
                                 str(_lbg[cnt+i]) + ';\n')
                        code += ('\t\tubg['+str(cnt+i)+'] = ' +
                                 str(_ubg[cnt+i]) + ';\n')
                    code += '\t}\n'
                cnt += con[0].size(1)
        return {'updateBounds': code}

    def _create_initSplines(self, father, problem):
        code = ''
        for label, child in father.children.items():
            for name in child._splines_prim:
                if name in child._variables:
                    code += '\tsplines_tf["'+name+'"] = '+name.upper()+'_TF;\n'
        return {'initSplines': code}

    def _create_transformSplines(self, father, problem, point2point):
        code, cnt = '', 0
        tf_len = len(problem.vehicles[0].basis)
        if point2point.__class__.__name__ == 'FixedTPoint2point':
            code += ('\tif(((current_time > 0) and ' +
                     'fabs(fmod(round(current_time*1000.)/1000., ' +
                     'horizon_time/' +
                     str(point2point.vehicles[0].knot_intervals)+')) <1.e-6)){\n')
            code += ('\t\tvector<double> spline_tf(' + str(len(problem.vehicles[0].basis)) + ');\n')
            for label, child in father.children.items():
                for name, var in child._variables.items():
                    if name in child._splines_prim:
                        if (len(child._splines_prim[name]['basis']) > tf_len):
                            tf_len = len(child._splines_prim[name]['basis'])
                            code += ('\t\tspline_tf.resize(' + str(tf_len)+');\n')
                        tf = 'splines_tf["'+name+'"]'
                        code += ('\t\tfor(int k=0; k<' +
                                 str(var.shape[1])+'; k++){\n')
                        code += ('\t\t\tfor(int i=0; i<' +
                                 str(var.shape[0])+'; i++){\n')
                        code += '\t\t\tspline_tf[i] = 0.0;\n'
                        code += ('\t\t\t\tfor(int j=0; j<' +
                                 str(var.shape[0])+'; j++){\n')
                        code += ('\t\t\t\t\tspline_tf[i] += '+tf +
                                 '[i][j]*variables['+str(cnt)+'+k*' +
                                 str(var.shape[0])+'+j];\n')
                        code += '\t\t\t\t}\n'
                        code += '\t\t\t}\n'
                        code += ('\t\t\tfor(int i=0; i<'+str(var.shape[0]) +
                                 '; i++){\n')
                        code += ('\t\t\t\tvariables['+str(cnt)+'+k*' +
                                 str(var.shape[0])+'+i] = spline_tf[i];\n')
                        code += '\t\t\t}\n'
                        code += '\t\t}\n'
                    cnt += var.size(1)
            code += '\t}\n'
        elif point2point.__class__.__name__ == 'FreeTPoint2point':
            raise Warning('Initialization for free time problem ' +
                          'not implemented (yet?).')
        return {'transformSplines': code}
