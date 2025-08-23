<#-- Antiquity Atlas rustic login. Extends the default layout. -->
<#import "template.ftl" as layout>
<@layout.registrationLayout displayInfo=false displayWide=false; section>
  <#if section = "title">
    Antiquity Atlas — Sign in
  </#if>

  <#if section = "header">
    <div class="aa-header">
      <img class="aa-logo" src="${url.resourcesPath}/img/logo.svg" alt="Antiquity Atlas logo" />
      <div class="aa-brand">
        <div class="aa-name">Antiquity Atlas</div>
        <div class="aa-tag">Exploration • Cartography • Archives</div>
      </div>
    </div>
  </#if>

  <#if section = "form">
    ${kcLoginForm()}
  </#if>

  <#if section = "footer">
    <div class="aa-footer">
      <span>© ${.now?string("yyyy")} Antiquity Atlas</span>
    </div>
  </#if>
</@layout.registrationLayout>
