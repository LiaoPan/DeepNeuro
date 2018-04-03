from __future__ import division

import os
import glob
import numpy as np
import tables
import copy

from deepneuro.augmentation.augment import Copy
from deepneuro.utilities.conversion import read_image_files
from deepneuro.data.data_group import DataGroup


class DataCollection(object):

    def __init__(self, data_directory=None, data_storage=None, modality_dict=None, spreadsheet_dict=None, value_dict=None, case_list=None, verbose=False):

        # Input vars
        self.data_directory = data_directory
        self.data_storage = data_storage
        self.modality_dict = modality_dict
        self.spreadsheet_dict = spreadsheet_dict
        self.value_dict = value_dict
        self.case_list = case_list
        self.verbose = verbose

        # Special behavior for augmentations
        self.augmentations = []
        self.preprocessors = []
        self.multiplier = 1

        # Empty vars
        self.cases = []
        self.total_cases = 0
        self.current_case = None
        self.data_groups = {}
        self.data_shape = None
        self.data_shape_augment = None

    def add_case(self, case_dict, case_name=None):

        # Currently only works for filepaths. Maybe add functionality for python data types, hdf5s?

        # Create DataGroups for this DataCollection.
        for modality_group in case_dict:
            if modality_group not in self.data_groups.keys():
                self.data_groups[modality_group] = DataGroup(modality_group)
                self.data_groups[modality_group].source = 'directory'

        # Search for modality files, and skip those missing with files modalities.
        for data_group, modality_group_files in case_dict.iteritems():

            self.data_groups[data_group].add_case(case_name, list(modality_group_files))
        
        self.cases.append(case_name)
        self.total_cases = len(self.cases)

    def fill_data_groups(self):

        if self.data_directory is not None:

            if self.verbose:
                print 'Gathering image data from...', self.data_directory, '\n'

            # TODO: Add section for spreadsheets.
            # TODO: Add section for values.

            # Create DataGroups for this DataCollection.
            for modality_group in self.modality_dict:
                if modality_group not in self.data_groups.keys():
                    self.data_groups[modality_group] = DataGroup(modality_group)
                    self.data_groups[modality_group].source = 'directory'

            # Iterate through directories.. Always looking for a better way to check optional list typing.
            if isinstance(self.data_directory, basestring):
                directory_list = sorted(glob.glob(os.path.join(self.data_directory, "*/")))
            else:
                directory_list = []
                for d in self.data_directory:
                    directory_list += glob.glob(os.path.join(d, "*/"))
                directory_list = sorted(directory_list)

            for subject_dir in directory_list:

                # If a predefined case list is provided, only choose these cases.
                if self.case_list is not None and os.path.basename(os.path.normpath(subject_dir)) not in self.case_list:
                    continue

                # Search for modality files, and skip those missing with files modalities.
                for data_group, modality_labels in self.modality_dict.iteritems():

                    modality_group_files = []
                    for modality in modality_labels:

                        # Iterate through patterns.. Always looking for a better way to check optional list typing.
                        if isinstance(modality, basestring):
                            target_file = glob.glob(os.path.join(subject_dir, modality))
                        else:
                            target_file = []
                            for m in modality:
                                target_file += glob.glob(os.path.join(subject_dir, m))

                        if len(target_file) == 1:
                            modality_group_files.append(target_file[0])
                        else:
                            print 'Error loading', modality, 'from', os.path.basename(os.path.dirname(subject_dir))
                            if len(target_file) == 0:
                                print 'No file found.\n'
                            else:
                                print 'Multiple files found.\n'
                            break

                    if len(modality_group_files) == len(modality_labels):
                        self.data_groups[data_group].add_case(os.path.abspath(subject_dir), list(modality_group_files))

                self.cases.append(os.path.abspath(subject_dir))

            self.total_cases = len(self.cases)
            print 'Found', self.total_cases, 'number of cases..'

        elif self.data_storage is not None:

            if self.verbose:
                print 'Gathering image metadata from...', self.data_storage

            open_hdf5 = tables.open_file(self.data_storage, "r")

            for data_group in open_hdf5.root._f_iter_nodes():
                if '_affines' not in data_group.name and '_casenames' not in data_group.name:

                    self.data_groups[data_group.name] = DataGroup(data_group.name)
                    self.data_groups[data_group.name].data = data_group
                    
                    # Affines and Casenames. Also not great praxis.
                    self.data_groups[data_group.name].data_affines = getattr(open_hdf5.root, data_group.name + '_affines')
                    self.data_groups[data_group.name].data_casenames = getattr(open_hdf5.root, data_group.name + '_casenames')

                    # Unsure if .source is needed. Convenient for now.
                    self.data_groups[data_group.name].source = 'storage'

                    # There's some double-counting here. TODO: revise, chop down one or the other.
                    self.data_groups[data_group.name].cases = xrange(data_group.shape[0])
                    self.data_groups[data_group.name].case_num = data_group.shape[0]
                    self.total_cases = data_group.shape[0]
                    self.cases = range(data_group.shape[0])

        else:
            print 'No directory or data storage file specified. No data groups can be filled.'

    def append_augmentation(self, augmentations, multiplier=None):

        # TODO: Add checks for unequal multiplier, or take multiplier specification out of the hands of individual augmentations.
        # TODO: Add checks for incompatible augmentations. Maybe make this whole thing better in general..

        if type(augmentations) is not list:
            augmentations = [augmentations]

        augmented_data_groups = []
        for augmentation in augmentations:
            for data_group_label in augmentation.data_groups.keys():
                augmented_data_groups += [data_group_label]

        # Unspecified data groups will be copied along.
        unaugmented_data_groups = [data_group for data_group in self.data_groups.keys() if data_group not in augmented_data_groups]
        if unaugmented_data_groups != []:
            augmentations += [Copy(data_groups=unaugmented_data_groups)]

        for augmentation in augmentations:
            for data_group_label in augmentation.data_groups.keys():
                augmentation.set_multiplier(multiplier)
                augmentation.append_data_group(self.data_groups[data_group_label])

        # This is so bad.
        for augmentation in augmentations:
            augmentation.initialize_augmentation()
            for data_group_label in augmentation.data_groups.keys():
                if augmentation.output_shape is not None:
                    self.data_groups[data_group_label].output_shape = augmentation.output_shape[data_group_label]
                self.data_groups[data_group_label].augmentation_cases.append(None) 
                self.data_groups[data_group_label].augmentation_strings.append('')

        # The total iterations variable allows for "total" augmentations later on.
        # For example, "augment until 5000 images is reached"
        total_iterations = multiplier
        self.multiplier *= multiplier

        self.augmentations.append({'augmentation': augmentations, 'iterations': total_iterations})

        return

    def append_preprocessor(self, preprocessors):

        if type(preprocessors) is not list:
            preprocessors = [preprocessors]

        for preprocessor in preprocessors:
            for data_group_label in preprocessor.data_groups:
                preprocessor.append_data_group(self.data_groups[data_group_label])
            self.preprocessors.append(preprocessor)

        # This is so bad.
        for preprocessor in preprocessors:
            for data_group_label in preprocessor.data_groups:
                if preprocessor.output_shape is not None:
                    self.data_groups[data_group_label].output_shape = preprocessor.output_shape[data_group_label]

        return

    def add_channel(self, case, input_data, data_group_labels=None, channel_dim=-1):
        
        # TODO: Add functionality for inserting channel at specific index, multiple channels

        if isinstance(input_data, basestring):
            input_data = read_image_files([input_data])

        if data_group_labels is None:
            data_groups = self.data_groups.values()
        else:
            data_groups = [self.data_groups[label] for label in data_group_labels]

        for data_group in data_groups:

            if data_group.base_case is None:
                self.load_case_data(case)

            data_group.base_case = np.concatenate((data_group.base_case, input_data[np.newaxis, ...]), axis=channel_dim)

            # # Perhaps should not use tuples for output shape.
            # output_shape = list(data_group.output_shape)
            # output_shape[channel_dim] = output_shape[channel_dim] + 1
            # data_group.output_shape = tuple(output_shape)

    def remove_channel(self, channel, data_group_labels=None, channel_dim=-1):

        # TODO: Add functionality for removing multiple channels

        if data_group_labels is None:
            data_groups = self.data_groups.values()
        else:
            data_groups = [self.data_groups[label] for label in data_group_labels]

        for data_group in data_groups:

            data_group.base_case = np.delete(data_group.base_case, channel, axis=channel_dim)

            # Perhaps should not use tuples for output shape.
            output_shape = list(data_group.output_shape)
            output_shape[channel_dim] -= 1
            data_group.output_shape = tuple(output_shape)

        return

    def get_data(self, case, data_group_labels=None):

        data_groups = self.get_data_groups(data_group_labels)

        if self.verbose:
            print 'Working on image.. ', case

        if case != self.current_case:
            self.load_case_data(case)

        recursive_augmentation_generator = self.recursive_augmentation(data_groups, augmentation_num=0)
        next(recursive_augmentation_generator)
                    
        return tuple([data_group.base_case for data_group in data_groups])

    def load_case_data(self, case, casename=None):

        data_groups = self.get_data_groups()

        # Don't remember what's going on here, maybe delete extra variable.
        # May have to do with indexing via hdf5s or file collections
        if casename is None:
            casename = case

        self.preprocess(case)

        for data_group in data_groups:

            data_group.base_case, data_group.base_affine = data_group.get_data(index=case, return_affine=True)

            if data_group.source == 'storage':
                data_group.base_casename = data_group.data_casenames[casename][0]
            else:
                data_group.base_case = data_group.base_case[np.newaxis, ...]
                data_group.base_casename = case

            if len(self.augmentations) != 0:
                data_group.augmentation_cases[0] = data_group.base_case

        self.current_case = case

    def preprocess(self, case):

        data_groups = self.get_data_groups()

        for data_group in data_groups:
            data_group.preprocessed_case = copy.copy(data_group.data[case])

        for preprocessor in self.preprocessors:
            preprocessor.reset()
            preprocessor.execute(case)

    # @profile
    def data_generator(self, data_group_labels=None, perpetual=False, case_list=None, yield_data=True, verbose=False, batch_size=1):

        data_groups = self.get_data_groups(data_group_labels)

        if case_list is None:
            case_list = self.cases

        # Kind of a funny way to do batches
        data_batch = [[] for data_group in data_groups]

        while True:

            np.random.shuffle(case_list)

            for case_idx, case_name in enumerate(case_list):

                if verbose:
                    print 'Working on image.. ', case_idx, 'at', case_name

                try:
                    self.load_case_data(case_name)
                except KeyboardInterrupt:
                    raise
                except:
                    print 'Hit error on', case_name, 'skipping.'
                    continue

                recursive_augmentation_generator = self.recursive_augmentation(data_groups, augmentation_num=0)

                for i in xrange(self.multiplier):
                    next(recursive_augmentation_generator)

                    if yield_data:
                        # TODO: Do this without if-statement and for loop?
                        for data_idx, data_group in enumerate(data_groups):
                            if len(self.augmentations) == 0:
                                data_batch[data_idx].append(data_group.base_case[0])
                            else:
                                data_batch[data_idx].append(data_group.augmentation_cases[-1][0])
                        if len(data_batch[0]) == batch_size:
                            # More strange indexing behavior. Shape inconsistency to be resolved.
                            yield tuple([np.stack(data_list) for data_list in data_batch])
                            data_batch = [[] for data_group in data_groups]
                    else:
                        yield True

            if not perpetual:
                yield None
                break

    # @profile
    def recursive_augmentation(self, data_groups, augmentation_num=0):

        if augmentation_num == len(self.augmentations):

            yield True
        
        else:

            # print 'BEGIN RECURSION FOR AUGMENTATION NUM', augmentation_num

            current_augmentation = self.augmentations[augmentation_num]

            for subaugmentation in current_augmentation['augmentation']:
                subaugmentation.reset(augmentation_num=augmentation_num)

            for iteration in xrange(current_augmentation['iterations']):

                for subaugmentation in current_augmentation['augmentation']:

                    subaugmentation.augment(augmentation_num=augmentation_num)
                    subaugmentation.iterate()

                lower_recursive_generator = self.recursive_augmentation(data_groups, augmentation_num + 1)

                # Why did I do this
                sub_augmentation_iterations = self.multiplier
                for i in xrange(augmentation_num + 1):
                    sub_augmentation_iterations /= self.augmentations[i]['iterations']

                for i in xrange(int(sub_augmentation_iterations)):
                    yield next(lower_recursive_generator)

            # print 'FINISH RECURSION FOR AUGMENTATION NUM', augmentation_num

    def clear_augmentations(self):

        # This function is basically a memory leak. Good for loading data and then immediately
        # using it to train. Not yet implemented

        self.augmentations = []
        self.multiplier = 1

        return

    def return_valid_cases(self, data_group_labels):

        valid_cases = []
        for case_name in self.cases:

            # This is terrible code. TODO: rewrite.
            missing_case = False
            for data_label, data_group in self.data_groups.iteritems():
                if data_label not in data_group_labels:
                    continue
                if case_name not in data_group.cases:
                    missing_case = True
                    break
            if not missing_case:
                valid_cases += [case_name]

        return valid_cases, len(valid_cases)

    def write_data_to_file(self, output_filepath=None, data_group_labels=None):

        """ Interesting question: Should all passed data_groups be assumed to have equal size? Nothing about hdf5 requires that, but it makes things a lot easier to assume.
        """

        # Sanitize Inputs
        if data_group_labels is None:
            data_group_labels = self.data_groups.keys()
        if output_filepath is None:
            raise ValueError('No output_filepath provided; data cannot be written.')

        # Create Data File
        # try:
        hdf5_file = self.create_hdf5_file(output_filepath, data_group_labels=data_group_labels)
        # except Exception as e:
            # os.remove(output_filepath)
            # raise e

        # Write data
        self.write_image_data_to_storage(data_group_labels)

        hdf5_file.close()

    def create_hdf5_file(self, output_filepath, data_group_labels=None):

        if data_group_labels is None:
            data_group_labels = self.data_groups.keys()

        hdf5_file = tables.open_file(output_filepath, mode='w')
        filters = tables.Filters(complevel=5, complib='blosc')

        for data_label, data_group in self.data_groups.iteritems():

            num_cases = self.total_cases * self.multiplier

            if num_cases == 0:
                raise Exception('WARNING: No cases found. Cannot write to file.')

            output_shape = data_group.get_shape()

            # Add batch dimension
            data_shape = (0,) + output_shape

            data_group.data_storage = hdf5_file.create_earray(hdf5_file.root, data_label, tables.Float32Atom(), shape=data_shape, filters=filters, expectedrows=num_cases)

            # Naming convention is bad here, TODO, think about this.
            data_group.casename_storage = hdf5_file.create_earray(hdf5_file.root, '_'.join([data_label, 'casenames']), tables.StringAtom(256), shape=(0, 1), filters=filters, expectedrows=num_cases)
            data_group.affine_storage = hdf5_file.create_earray(hdf5_file.root, '_'.join([data_label, 'affines']), tables.Float32Atom(), shape=(0, 4, 4), filters=filters, expectedrows=num_cases)

        return hdf5_file

    def write_image_data_to_storage(self, data_group_labels=None, repeat=1):

        # This is very shady. Currently trying to reconcile between loading data from a
        # directory and loading data from an hdf5.
        if self.data_directory is not None:
            storage_cases, total_cases = self.return_valid_cases(data_group_labels)
        else:
            storage_cases, total_cases = self.cases, self.total_cases

        storage_data_generator = self.data_generator(data_group_labels, case_list=storage_cases, yield_data=False)

        for i in xrange(self.multiplier * total_cases):

            output = next(storage_data_generator)

            if output:
                for data_group_label in data_group_labels:
                    self.data_groups[data_group_label].write_to_storage()

        return

    def get_data_groups(self, data_group_labels=None):

        if data_group_labels is None:
            data_groups = self.data_groups.values()
        else:
            data_groups = [self.data_groups[label] for label in data_group_labels]

        return data_groups


if __name__ == '__main__':
    pass
