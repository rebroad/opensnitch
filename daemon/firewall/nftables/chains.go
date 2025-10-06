package nftables

import (
	"fmt"
	"strings"

	"github.com/evilsocket/opensnitch/daemon/firewall/nftables/exprs"
	"github.com/evilsocket/opensnitch/daemon/log"
	"github.com/google/nftables"
)

// getChainKey returns the identifier that will be used to link chains and rules.
// When adding a new chain the key is stored, then later when adding a rule we get
// the chain that the rule belongs to by this key.
func getChainKey(name string, table *nftables.Table) string {
	if table == nil {
		return ""
	}
	return fmt.Sprintf("%s-%s-%d", name, table.Name, table.Family)
}

// GetChain gets an existing chain
func GetChain(name string, table *nftables.Table) *nftables.Chain {
	key := getChainKey(name, table)
	if ch, ok := sysChains.Load(key); ok {
		return ch.(*nftables.Chain)
	}
	return nil
}

// AddChain adds a new chain to nftables.
// https://wiki.nftables.org/wiki-nftables/index.php/Netfilter_hooks#Priority_within_hook
func (n *Nft) AddChain(name, table, family string, priority *nftables.ChainPriority, ctype nftables.ChainType, hook *nftables.ChainHook, policy nftables.ChainPolicy) *nftables.Chain {
	if family == "" {
		family = exprs.NFT_FAMILY_INET
	}
	tbl := n.GetTable(table, family)
	if tbl == nil {
		log.Error("%s addChain, Error getting table: %s, %s", logTag, table, family)
		return nil
	}

	var chain *nftables.Chain
	// Verify if the chain already exists, and reuse it if it does.
	// In some systems it fails adding a chain when it already exists, whilst in others
	// it doesn't.
	key := getChainKey(name, tbl)
	chain = n.GetChain(name, tbl, family)
	if chain != nil {
		if _, exists := sysChains.Load(key); exists {
			sysChains.Delete(key)
		}
		chain.Policy = &policy
		n.Conn.AddChain(chain)
	} else {
		// nft list chains
		chain = n.Conn.AddChain(&nftables.Chain{
			Name:     strings.ToLower(name),
			Table:    tbl,
			Type:     ctype,
			Hooknum:  hook,
			Priority: priority,
			Policy:   &policy,
		})
		if chain == nil {
			log.Debug("%s AddChain() chain == nil", logTag)
			return nil
		}
	}

	sysChains.Store(key, chain)
	return chain
}

// GetChain checks if a chain in the given table exists.
func (n *Nft) GetChain(name string, table *nftables.Table, family string) *nftables.Chain {
	if chains, err := n.Conn.ListChains(); err == nil {
		for _, c := range chains {
			if name == c.Name && table.Name == c.Table.Name && GetFamilyCode(family) == c.Table.Family {
				return c
			}
		}
	}
	return nil
}

// regular chains are user-defined chains, to better organize fw rules.
// https://wiki.nftables.org/wiki-nftables/index.php/Configuring_chains#Adding_regular_chains
func (n *Nft) addRegularChain(name, table, family string) error {
	tbl := n.GetTable(table, family)
	if tbl == nil {
		return fmt.Errorf("%s addRegularChain, Error getting table: %s, %s", logTag, table, family)
	}

	chain := n.Conn.AddChain(&nftables.Chain{
		Name:  name,
		Table: tbl,
	})
	if chain == nil {
		return fmt.Errorf("%s error adding regular chain: %s", logTag, name)
	}
	key := getChainKey(name, tbl)
	sysChains.Store(key, chain)

	return nil
}

// AddInterceptionChains adds the needed chains to intercept traffic.
func (n *Nft) AddInterceptionChains() error {
	var filterPolicy nftables.ChainPolicy
	var manglePolicy nftables.ChainPolicy
	filterPolicy = nftables.ChainPolicyAccept
	manglePolicy = nftables.ChainPolicyAccept

	tbl := n.GetTable(exprs.TABLE_OPENSNITCH, exprs.NFT_FAMILY_INET)
	if tbl != nil {
		key := getChainKey(exprs.CHAIN_FILTER_INPUT, tbl)
		ch, found := sysChains.Load(key)
		if key != "" && found {
			filterPolicy = *ch.(*nftables.Chain).Policy
		}
	}
	if tbl != nil {
		key := getChainKey(exprs.CHAIN_MANGLE_OUTPUT, tbl)
		ch, found := sysChains.Load(key)
		if key != "" && found {
			manglePolicy = *ch.(*nftables.Chain).Policy
		}
	}

	// nft list tables
	n.AddChain(exprs.CHAIN_FILTER_INPUT, exprs.TABLE_OPENSNITCH, exprs.NFT_FAMILY_INET,
		nftables.ChainPriorityFilter, nftables.ChainTypeFilter, nftables.ChainHookInput, filterPolicy)
	if !n.Commit() {
		return fmt.Errorf("Error adding DNS interception chain filter_input-opensnitch-inet")
	}
	n.AddChain(exprs.CHAIN_MANGLE_OUTPUT, exprs.TABLE_OPENSNITCH, exprs.NFT_FAMILY_INET,
		nftables.ChainPriorityMangle, nftables.ChainTypeRoute, nftables.ChainHookOutput, manglePolicy)
	if !n.Commit() {
		log.Error("(1) Error adding interception chain mangle_output-opensnitch-inet, trying with type Filter instead of Route")

		// Workaround for kernels 4.x and maybe others.
		// @see firewall/nftables/utils.go:GetChainPriority()
		chainPrio, chainType := GetChainPriority(exprs.NFT_FAMILY_INET, exprs.NFT_CHAIN_MANGLE, exprs.NFT_HOOK_OUTPUT)
		n.AddChain(exprs.CHAIN_MANGLE_OUTPUT, exprs.TABLE_OPENSNITCH, exprs.NFT_FAMILY_INET,
			chainPrio, chainType, nftables.ChainHookOutput, manglePolicy)
		if !n.Commit() {
			return fmt.Errorf("(2) Error adding interception chain mangle_output-opensnitch-inet with type Filter. Report it on github please, specifying the distro and the kernel")
		}
	}

	return nil
}

// DelChain deletes a chain from the system.
func (n *Nft) DelChain(chain *nftables.Chain) error {
	n.Conn.DelChain(chain)
	sysChains.Delete(getChainKey(chain.Name, chain.Table))
	if !n.Commit() {
		return fmt.Errorf("[nftables] error deleting chain %s, %s", chain.Name, chain.Table.Name)
	}

	return nil
}

// backupExistingChains saves ALL existing chain policies (both Accept and Drop).
// This preserves the user's original security configuration instead of assuming
// everything should be Accept, which is a security vulnerability.
func (n *Nft) backupExistingChains() {
	if chains, err := n.Conn.ListChains(); err == nil {
		for _, c := range chains {
			if c.Policy != nil {
				// Backup ALL policies, not just Accept - preserve user's security configuration
				log.Debug("%s backing up existing chain with policy %s: %s, %s", logTag,
					*c.Policy, c.Name, c.Table.Name)
				origSysChains[getChainKey(c.Name, c.Table)] = c
			}
		}
	}
}

func (n *Nft) restoreBackupChains() {
	for _, c := range origSysChains {
		// Restore the ORIGINAL policy, not force it to Accept
		// This preserves the user's security configuration
		log.Debug("%s Restoring chain policy to original %s: %s, %s", logTag,
			*c.Policy, c.Name, c.Table.Name)
		// Don't modify the policy - restore it as-is
		n.Conn.AddChain(c)
	}
	n.Commit()
}
