<template>
  <div class="ops-setting-auth">
    <a-tabs class="ops-tab" v-model="activeKey" @change="changeActiveKey">
      <a-tab-pane v-for="item in authList" :key="item.value">
        <span slot="tab">
          {{ item.label }}
          <a-icon v-if="enable_list.find((en) => en.auth_type === item.value)" type="check-circle" theme="filled" />
        </span>
        <div class="setting-auth">
          <components :ref="item.value" :is="item.value === 'OIDC' ? 'OAUTH2' : item.value" :data_type="item.value" />
          <a-row>
            <a-col :offset="item.value === 'AuthCommonConfig' ? 5 : 3">
              <a-space>
                <a-button :loading="loading" type="primary" @click="handleSave">{{ $t('save') }}</a-button>
                <template v-if="item.value === 'LDAP'">
                  <a-button :loading="loading" ghost type="primary" @click="handleTest('connect')">{{
                    $t('cs.auth.testConnect')
                  }}</a-button>
                  <a-button :loading="loading" ghost type="primary" @click="handleTest('login')">{{
                    $t('cs.auth.testLogin')
                  }}</a-button>
                </template>
                <a-button :loading="loading" @click="handleReset">{{ $t('reset') }}</a-button>
              </a-space>
            </a-col>
          </a-row>
        </div>
        <LoginModal v-if="item.value === 'LDAP'" ref="loginModal" @handleOK="(values) => handleTest('login', values)" />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script>
import _ from 'lodash'
import LDAP from './ldap.vue'
import CAS from './cas.vue'
import AuthCommonConfig from './common.vue'
import OAUTH2 from './oauth2.vue'
import LoginModal from './loginModal.vue'
import { getAuthData, postAuthData, putAuthData, getAuthDataEnable, testLDAP } from '@/api/auth'
export default {
  name: 'Auth',
  components: { LDAP, CAS, AuthCommonConfig, OAUTH2, LoginModal },
  data() {
    return {
      activeKey: 'LDAP',
      dataTypeId: null,
      loading: false,
      enable_list: [],
    }
  },
  mounted() {
    this.changeActiveKey()
    this.getAuthDataEnable()
  },
  computed: {
    authList() {
      return [
        {
          value: 'LDAP',
          label: 'LDAP',
        },
        {
          value: 'CAS',
          label: 'CAS',
        },
        {
          value: 'OAUTH2',
          label: 'OAUTH2',
        },
        {
          value: 'OIDC',
          label: 'OIDC',
        },
        {
          value: 'AuthCommonConfig',
          label: this.$t('cs.auth.common'),
        },
      ]
    },
  },
  methods: {
    getAuthDataEnable() {
      getAuthDataEnable().then((res) => {
        this.enable_list = res.enable_list
      })
    },
    changeActiveKey() {
      getAuthData(this.activeKey).then((res) => {
        const _res = _.cloneDeep(res)
        this.$refs[this.activeKey][0].setData(_res?.data ?? null)
        if (_res && JSON.stringify(_res) !== '{}') {
          this.dataTypeId = _res.id
        } else {
          this.dataTypeId = null
        }
      })
    },
    handleSave() {
      this.$refs[this.activeKey][0].getData(async (data) => {
        this.loading = true
        if (this.dataTypeId) {
          await putAuthData(this.activeKey, this.dataTypeId, { data }).finally(() => {
            this.loading = false
          })
        } else {
          await postAuthData(this.activeKey, { data }).finally(() => {
            this.loading = false
          })
        }
        this.$message.success(this.$t('saveSuccess'))
        this.changeActiveKey()
        this.getAuthDataEnable()
      })
    },
    handleReset() {
      this.changeActiveKey()
    },
    handleTest(type, values = null) {
      this.$refs[this.activeKey][0].getData(async (data) => {
        if (type === 'login' && !values) {
          this.$refs.loginModal[0].open()
        } else {
          this.loading = true
          let _data = _.cloneDeep(data)
          if (values) {
            _data = {
              ..._data,
              ...values,
            }
          }
          testLDAP({ data: _data, test_type: type })
            .then((res) => {
              this.$message.success(this.$t('cs.auth.testSuccess'))
            })
            .finally(() => {
              this.loading = false
            })
        }
      })
    },
  },
}
</script>

<style lang="less" scoped>
.ops-setting-auth {
  padding: 20px;
  padding-top: 0;
  background-color: #fff;
  border-radius: @border-radius-box;
  overflow: auto;
  margin-bottom: -24px;
  height: calc(100vh - 64px);
}
.setting-auth {
  background-color: #fff;
  height: calc(100vh - 150px);
  overflow: auto;
  border-radius: 0 5px 5px 5px;
}
</style>

<style lang="less">
.setting-auth {
  .jsoneditor-outer {
    height: var(--custom-height) !important;
    border: 1px solid @primary-color;
  }
  div.jsoneditor-menu {
    background-color: @primary-color;
  }
  .jsoneditor-modes {
    display: none;
  }
}
</style>
