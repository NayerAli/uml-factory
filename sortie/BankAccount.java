import java.util.ArrayList;
import java.util.List;

/**
 * Représente un compte bancaire avec solde et opérations possibles.
 */
public class BankAccount {

    private double balance;

    /** Association directionnelle : cartes liées à ce compte. */
    private List<CreditCard> linkedCard = new ArrayList<>();

    /** Association bidirectionnelle : titulaire principal du compte. */
    private Customer primaryHolder;

    public BankAccount() {
    }

    public double getBalance() {
        return balance;
    }

    public void setBalance(double balance) {
        this.balance = balance;
    }

    public List<CreditCard> getLinkedCard() {
        return linkedCard;
    }

    public void setLinkedCard(List<CreditCard> linkedCard) {
        this.linkedCard = linkedCard;
    }

    public Customer getPrimaryHolder() {
        return primaryHolder;
    }

    public void setPrimaryHolder(Customer primaryHolder) {
        this.primaryHolder = primaryHolder;
    }

    /**
     * Ajoute une carte de crédit aux cartes liées à ce compte.
     */
    public void addLinkedCard(CreditCard card) {
        if (card != null && !linkedCard.contains(card)) {
            linkedCard.add(card);
        }
    }

    /**
     * Retire une carte de crédit des cartes liées à ce compte.
     */
    public void removeLinkedCard(CreditCard card) {
        linkedCard.remove(card);
    }

    public void deposit() {
        // TODO: implémenter le dépôt (aucun montant fourni dans le diagramme)
    }

    public void withdraw() {
        // TODO: implémenter le retrait (aucun montant fourni dans le diagramme)
    }
}
