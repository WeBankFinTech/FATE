#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  Copyright 2019 The FATE Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import random

import numpy as np

from federatedml.feature.instance import Instance
from federatedml.secure_information_retrieval.base_secure_information_retrieval import \
    BaseSecureInformationRetrieval, CryptoExecutor
from federatedml.param.sir_param import SecureInformationRetrievalParam
from federatedml.secureprotol.oblivious_transfer.hauck_oblivious_transfer.hauck_oblivious_transfer_receiver import \
    HauckObliviousTransferReceiver
from federatedml.secureprotol.symmetric_encryption.py_aes_encryption import AESDecryptKey
from federatedml.secureprotol.symmetric_encryption.pohlig_hellman_encryption import PohligHellmanCipherKey
from federatedml.util import consts, abnormal_detection, LOGGER


MODEL_PARAM_NAME = 'SecureInformationRetrievalParam'
MODEL_META_NAME = 'SecureInformationRetrievalMeta'


class SecureInformationRetrievalGuest(BaseSecureInformationRetrieval):
    def __init__(self):
        super(SecureInformationRetrievalGuest, self).__init__()
        self.oblivious_transfer = None
        self.target_block_index = None      # k-th block message is expected to obtain, with k in {0, 1, ..., N-1}

        # The following parameter restricts the range of the block number
        self.security_scale = np.log(500)   # block_num = 2 * exp(security_scale * security_level)

    def _init_model(self, param: SecureInformationRetrievalParam):
        self._init_base_model(param)

        if self.model_param.oblivious_transfer_protocol == consts.OT_HAUCK:
            self.oblivious_transfer = HauckObliviousTransferReceiver()
        else:
            LOGGER.error("SIR only supports Hauck's OT")
            raise ValueError("SIR only supports Hauck's OT")

        if self.model_param.commutative_encryption == consts.CE_PH:
            self.commutative_cipher = CryptoExecutor(PohligHellmanCipherKey.generate_key(self.model_param.key_size))
        else:
            LOGGER.error("SIR only supports Pohlig-Hellman encryption")
            raise ValueError("SIR only supports Pohlig-Hellman encryption")

    def fit(self, data_inst):
        """

        :param data_inst: Table, only the key column of the Table is used
        :return:
        """
        # 0. Raw retrieval
        if self.model_param.raw_retrieval or self.security_level == 0:
            LOGGER.info("enter raw information retrieval guest")
            abnormal_detection.empty_table_detection(data_inst)
            data_output = self._raw_information_retrieval(data_inst)
            self._display_result(block_num='N/A')
            return data_output

        # 1. Data pre-processing
        LOGGER.info("enter secure information retrieval guest")
        abnormal_detection.empty_table_detection(data_inst)
        self._parse_security_level(data_inst)
        if not self._check_oblivious_transfer_condition():
            self._failure_response()

        # 2. Sync commutative cipher public knowledge, block num and init
        self._sync_commutative_cipher_public_knowledge()
        self.commutative_cipher.init()
        LOGGER.info("commutative cipher key generated")

        # 3. 1st ID encryption and exchange
        # g: guest's plaintext
        # Eg: guest's ciphertext
        # EEg: guest's doubly encrypted ciphertext
        # h, Eh, EEh: host
        # i, Ei, EEi: intersection
        # record converted string id in case of non-ascii
        recorded_k_data = data_inst.map(lambda k, v: BaseSecureInformationRetrieval.record_original_id(k, v))
        id_list_guest_first = self._encrypt_id(data_inst)      # (Eg, -1)
        LOGGER.info("encrypted guest id for the 1st time")
        id_list_host_first = self._exchange_id_list(id_list_guest_first)              # send (Eg, -1), get (Eh, -1)

        # 4. 2nd ID encryption, receive doubly encrypted ID list from host
        id_list_host_second = self._encrypt_id(id_list_host_first, reserve_original_key=True)    # (Eh, EEh)
        LOGGER.info("encrypted guest id for the 2nd time")
        id_list_host_second_only = id_list_host_second.map(lambda k, v: (v, -1))     # (EEh, -1)
        id_list_guest_second = self._sync_doubly_encrypted_id_list()       # get (EEg, -1)

        # 5. Find intersection and re-index
        id_list_intersect = self._find_intersection(
            id_list_guest_second, id_list_host_second_only)     # (EEi, -1)
        LOGGER.info("intersection found")

        # 6. Send the re-indexed doubly encrypted ID to host
        self._fake_blocks(id_list_intersect, id_list_host_second_only)  # List[(EEi, -1)]
        LOGGER.info("faked blocks for obfuscation")

        # 7. Wait for host to restore value for the intersection
        LOGGER.info("waiting for host to restore interested values for the intersection")

        # 8. Execute OT as receiver
        LOGGER.info("enter oblivious transfer protocol as a receiver")
        target_key = self.oblivious_transfer.key_derivation(self.target_block_index)
        LOGGER.info("oblivious transfer key derived")

        # 9. Wait for host to encrypt and transmit, and then receive the encrypted interested values
        id_block_ciphertext, nonce = self._iteratively_get_encrypted_values()
        LOGGER.info("got encrypted interested values and nonce")
        target_block_cipher_id = self._non_committing_decrypt(
            id_block_ciphertext, nonce, target_key)  # (Eright, val)
        LOGGER.info("used the right key to decrypt the wanted values")

        # 10. Encrypt again and send to host
        target_block_cipher_cipher_id = self._composite_encrypt(target_block_cipher_id)      # (EEright, val)
        self._sync_intersect_cipher_cipher(
            target_block_cipher_cipher_id.mapValues(lambda v: -1))       # send (EEright, -1)

        # 11. Get decrypted result from host, and decrypt again
        id_list_intersect_cipher_id = self._sync_intersect_cipher()        # get (EEright, Eright_host)
        id_list_intersect_cipher_id = self._composite_decrypt(id_list_intersect_cipher_id)        # (EEright, right)

        # 12. Merge result
        data_output = self._merge(target_block_cipher_cipher_id, id_list_intersect_cipher_id)
        data_output = recorded_k_data.join(data_output, lambda v1, v2: (v1, v2))
        data_output = data_output.map(lambda k, v: (v[0], v[1]))
        data_output = self._compensate_set_difference(data_inst, data_output)
        self._display_result()
        LOGGER.info("secure information retrieval finished")

        return data_output

    def _sync_nonce_list(self, nonce=None, time=0):
        nonce_list_result = self.transfer_variable.nonce_list.get(idx=0,
                                                                  suffix=(time,))
        # nonce_list_result = federation.get(name=self.transfer_variable.nonce_list.name,
        #                                    tag=self.transfer_variable.generate_transferid(
        #                                        self.transfer_variable.nonce_list, time),
        #                                    idx=0)
        LOGGER.info("Got {}-th nonce list from host".format(time))
        return nonce_list_result

    @staticmethod
    def _merge(id_map1, id_map2):
        """

        :param id_map1: (a, b)
        :param id_map2: (a, c)
        :return: (c, b)
        """
        merge_table = id_map1.join(id_map2, lambda v, u: (u, v))
        return merge_table.map(lambda k, v: (v[0], Instance(label=v[1], features=[])))

    def _composite_decrypt(self, id_list):
        """
        k, v -> k, Dv
        :param id_list:
        :return:
        """
        return self.commutative_cipher.map_values_decrypt(id_list, mode=1)

    def _composite_encrypt(self, id_list):
        """
        k, v -> Ek, v
        :param id_list:
        :return:
        """
        return self.commutative_cipher.map_encrypt(id_list, mode=2)

    def _decrypt_value(self, id_list):
        """

        :param id_list:
        :return:
        """

    def _sync_intersect_cipher(self, id_list=None):
        id_list_intersect_cipher = self.transfer_variable.intersect_cipher.get(idx=0)
        # id_list_intersect_cipher = federation.get(
        #     name=self.transfer_variable.intersect_cipher.name,
        #     tag=self.transfer_variable.generate_transferid(self.transfer_variable.intersect_cipher),
        #     idx=0
        # )
        LOGGER.info("got intersect cipher from host")
        return id_list_intersect_cipher

    def _sync_intersect_cipher_cipher(self, id_list):
        self.transfer_variable.intersect_cipher_cipher.remote(id_list,
                                                              role=consts.HOST,
                                                              idx=0)
        # federation.remote(obj=id_list,
        #                   name=self.transfer_variable.intersect_cipher_cipher.name,
        #                   tag=self.transfer_variable.generate_transferid(
        #                       self.transfer_variable.intersect_cipher_cipher),
        #                   role=consts.HOST,
        #                   idx=0)
        LOGGER.info("sent intersect cipher cipher to host")

    def _non_committing_decrypt(self, id_block_ciphertext, nonce, target_key):
        """
        Use non-committing cipher to encrypt id blocks
        :param id_block_ciphertext: (Ei, Eval)
        :param nonce: bytes
        :param target_key: ObliviousTransferKey
        :return:
        """
        if self.model_param.non_committing_encryption == consts.AES:
            aes_key = CryptoExecutor(AESDecryptKey(key=target_key.key, nonce=nonce))
        else:
            raise ValueError("only supports AES cipher for non-committing decryption")

        return aes_key.map_values_decrypt(id_block_ciphertext, mode=0)

    def _transmit_value_ciphertext(self, id_block=None, time=0):
        id_blocks = self.transfer_variable.id_blocks_ciphertext.get(idx=0,
                                                                    suffix=(time,))
        # id_blocks = federation.get(name=self.transfer_variable.id_blocks_ciphertext.name,
        #                            tag=self.transfer_variable.generate_transferid(
        #                                self.transfer_variable.id_blocks_ciphertext, time),
        #                            idx=0)
        LOGGER.info("got {}-th id block ciphertext from host".format(time))
        return id_blocks

    def _decrypt_id_list(self, id_list):
        """

        :param id_list: (EEe, v)
        :return: (Ee, v)
        """
        return self.commutative_cipher.map_decrypt(id_list, mode=2)

    def _sync_natural_indexation(self, id_list, time):
        self.transfer_variable.natural_indexation.remote(id_list,
                                                         suffix=(time,),
                                                         role=consts.HOST,
                                                         idx=0)
        # federation.remote(obj=id_list,
        #                   name=self.transfer_variable.natural_indexation.name,
        #                   tag=self.transfer_variable.generate_transferid(
        #                       self.transfer_variable.natural_indexation, time),
        #                   role=consts.HOST,
        #                   idx=0)
        LOGGER.info("sent naturally indexed block {} to host".format(time))

    def _fake_blocks(self, id_list_intersect, id_list_host, replacement=True):
        """
        Randomly sample self.block_num - 1 blocks with the same size as id_list_intersect from id_list_host
        :param id_list_intersect: Table in the form (intersect_ENC_id, -1)
        :param id_list_host: Table in the form (ENC_id, -1)
        :param replacement: bool
        :return: id_list_array: List[Table] with disjoint (ENC_id, -1) Tables
        """
        intersect_count = id_list_intersect.count()
        self.target_block_index = random.randint(0, self.block_num - 1)
        for i in range(self.block_num):
            if i == self.target_block_index:
                id_block = id_list_intersect
            else:
                id_block = self.take_exact_sample(data_inst=id_list_host, exact_num=intersect_count)
                if not replacement:
                    id_list_host = id_list_host.subtractByKey(id_block)
            id_block = self._decrypt_id_list(id_block)
            self._sync_natural_indexation(id_block, time=i)

    @staticmethod
    def _id_list_array_indexation(id_list_array):
        """

        :param id_list_array: List(Table)
        :return:
        """
        for i in range(len(id_list_array)):
            id_list_array[i].mapValues(lambda v: i)
        return id_list_array

    @staticmethod
    def _find_intersection(id_list_guest, id_list_host):
        """
        Find the intersection set of ENC_id
        :param id_list_guest: Table in the form (EEg, -1)
        :param id_list_host: Table in the form (EEh, -1)
        :return: Table in the form (EEi, -1)
        """
        return id_list_guest.join(id_list_host, lambda v, u: -1)

    def _sync_doubly_encrypted_id_list(self, id_list=None):
        id_list_guest = self.transfer_variable.doubly_encrypted_id_list.get(idx=0)
        # id_list_guest = federation.get(name=self.transfer_variable.doubly_encrypted_id_list.name,
        #                                tag=self.transfer_variable.generate_transferid(
        #                                    self.transfer_variable.doubly_encrypted_id_list),
        #                                idx=0)
        LOGGER.info("got doubly encrypted id list from host")
        return id_list_guest

    def _parse_security_level(self, data_instance):
        data_count_guest = data_instance.count()

        # block_num = 2 * exp(scale * level)
        self.block_num = int(np.ceil(2 * np.exp(self.security_scale * self.security_level)))
        LOGGER.info("parsed block num = {}".format(self.block_num))

        self._sync_block_num()

    def _exchange_id_list(self, id_list_guest):
        self.transfer_variable.id_ciphertext_list_exchange_g2h.remote(id_list_guest,
                                                                      role=consts.HOST,
                                                                      idx=0)
        # federation.remote(obj=id_list_guest,
        #                   name=self.transfer_variable.id_ciphertext_list_exchange_g2h.name,
        #                   tag=self.transfer_variable.generate_transferid(
        #                       self.transfer_variable.id_ciphertext_list_exchange_g2h),
        #                   role=consts.HOST,
        #                   idx=0)
        LOGGER.info("sent id 1st ciphertext list to host")
        id_list_host = self.transfer_variable.id_ciphertext_list_exchange_h2g.get(idx=0)
        # id_list_host = federation.get(name=self.transfer_variable.id_ciphertext_list_exchange_h2g.name,
        #                               tag=self.transfer_variable.generate_transferid(
        #                                   self.transfer_variable.id_ciphertext_list_exchange_h2g),
        #                               idx=0)
        LOGGER.info("got id 1st ciphertext list from host")
        return id_list_host

    def _encrypt_id(self, data_instance, reserve_original_key=False):
        """
        Encrypt the key (ID) column of the input Table
        :param data_instance: Table
                reserve_original_key: (ori_key, enc_key) if reserve_original_key == True, otherwise (enc_key, -1)
        :return:
        """
        if reserve_original_key:
            return self.commutative_cipher.map_encrypt(data_instance, mode=0)
        else:
            return self.commutative_cipher.map_encrypt(data_instance, mode=1)
        # if reserve_original_key:
        #     return data_instance.mapValues(lambda k: (k, self.commutative_cipher.encrypt(k)))
        # else:
        #     return data_instance.map(lambda k, v: (self.commutative_cipher.encrypt(k), -1))

    def _sync_commutative_cipher_public_knowledge(self):
        self.transfer_variable.commutative_cipher_public_knowledge.remote(self.commutative_cipher,
                                                                          role=consts.HOST,
                                                                          idx=0)
        # federation.remote(obj=self.commutative_cipher,
        #                   name=self.transfer_variable.commutative_cipher_public_knowledge.name,
        #                   tag=self.transfer_variable.generate_transferid(
        #                       self.transfer_variable.commutative_cipher_public_knowledge),
        #                   role=consts.HOST,
        #                   idx=0)
        LOGGER.info("sent commutative cipher public knowledge to host {}".format(self.commutative_cipher))

    def _raw_information_retrieval(self, data_instance):
        self.transfer_variable.raw_id_list.remote(data_instance.map(lambda k, v: (k, -1)),
                                                  role=consts.HOST,
                                                  idx=0)
        # federation.remote(obj=data_instance.map(lambda k, v: (k, -1)),
        #                   name=self.transfer_variable.raw_id_list.name,
        #                   tag=self.transfer_variable.generate_transferid(self.transfer_variable.raw_id_list),
        #                   role=consts.HOST,
        #                   idx=0)
        LOGGER.info("sent raw id list to host")

        data_output = self.transfer_variable.raw_value_list.get(idx=0)
        # data_output = federation.get(name=self.transfer_variable.raw_value_list.name,
        #                              tag=self.transfer_variable.generate_transferid(
        #                                  self.transfer_variable.raw_value_list),
        #                              idx=0)
        LOGGER.info("got raw value list from host")

        data_output = self._compensate_set_difference(data_instance, data_output)

        return data_output

    @staticmethod
    def take_exact_sample(data_inst, exact_num):
        """
        Sample an exact number of instances from a Table
        :param data_inst: Table
        :param exact_num: int
        :return: Table
        """
        """
        data_inst_count = data_inst.count()
        rate = exact_num / data_inst_count
        while True:
            sample_inst = data_inst.sample(fraction=rate)
            if sample_inst.count() >= exact_num:
                break
        if sample_inst.count() != exact_num:
            # diff = sample_inst.count() - exact_num
            # diff_list = sample_inst.take(diff)
            # for k, _ in diff_list:
                #sample_inst.delete(k=k)
            sample_inst_list = sample_inst.take(exact_num)
            from fate_arch.session import computing_session as session
            sample_inst = session.parallelize(sample_inst_list,
                                              partition=sample_inst.partitions,
                                              include_key=True)
        """
        sample_inst = data_inst.sample(num=exact_num)
        return sample_inst

    def _sync_block_num(self):
        self.transfer_variable.block_num.remote(self.block_num,
                                                role=consts.HOST,
                                                idx=0)
        # federation.remote(obj=self.block_num,
        #                   name=self.transfer_variable.block_num.name,
        #                   tag=self.transfer_variable.generate_transferid(self.transfer_variable.block_num),
        #                   role=consts.HOST,
        #                   idx=0)
        LOGGER.info("sent block num {} to host".format(self.block_num))

    def _compensate_set_difference(self, original_data, data_output):
        self.coverage = data_output.count() / original_data.count()
        original_data = original_data.mapValues(lambda v: Instance(label="unretrieved", features=[]))
        # LOGGER.debug(f"original data features is {list(original_data.collect())[0][1].features}")
        # LOGGER.debug(f"original data label is {list(original_data.collect())[0][1].label}")

        data_output = original_data.union(data_output, lambda v, u: u)
        # LOGGER.debug(f"data_output features after union is {list(data_output.collect())[0][1].features}")
        # LOGGER.debug(f"data_output label after union is {list(data_output.collect())[0][1].label}")

        data_output = self._set_schema(data_output, id_name='id', label_name='retrieved_value')
        self._sync_coverage(original_data)
        return data_output

    def _sync_coverage(self, data_instance):
        self.transfer_variable.coverage.remote(self.coverage * data_instance.count(),
                                               role=consts.HOST,
                                               idx=0)
        # federation.remote(obj=self.coverage * data_instance.count(),
        #                   name=self.transfer_variable.coverage.name,
        #                   tag=self.transfer_variable.generate_transferid(self.transfer_variable.coverage),
        #                   role=consts.HOST,
        #                   idx=0)
        LOGGER.info("sent coverage {} to host".format(self.coverage * data_instance.count()))

    def _iteratively_get_encrypted_values(self):
        """

        :return: Table, bytes
        """
        id_block_ciphertext = None
        nonce = None
        for i in range(self.block_num):
            id_block = self._transmit_value_ciphertext(time=i)     # List[(Ei, Eval)]
            nonce_inst = self._sync_nonce_list(time=i)

            if i != self.target_block_index:
                pass
            else:
                id_block_ciphertext = id_block
                nonce = nonce_inst

            self.transfer_variable.block_confirm.remote(True,
                                                        suffix=(i,),
                                                        role=consts.HOST,
                                                        idx=0)

        return id_block_ciphertext, nonce
